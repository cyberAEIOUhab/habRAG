"""
生产迁移：本地 Chroma → Zilliz Cloud Serverless
================================================
把本地 habsburg 集合的全部 chunk（向量 + 正文 + 元数据）灌入 Zilliz Cloud。

- 向量直接复制，**不重新调用 embedding API**
- 目标集合名与本地一致（habsburg），集合 schema 见 build_schema()
- 幂等：--drop 会先删掉同名集合重建；不加 --drop 则续传到已有集合（跳过已存在的 chunk_id）

用法：
    $env:ZILLIZ_URI   = "https://<cluster>.serverless.ali-cn-hangzhou.cloud.zilliz.com.cn"
    $env:ZILLIZ_TOKEN = "<api key>"
    python migrate_to_zilliz.py --drop
"""
import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(_HERE, "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)
os.chdir(_HERE)
sys.path.insert(0, _HERE)

import numpy as np

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()
NAME = "habsburg"
DIM = 1024
BATCH = 500

# ★★ analyzer 已由 recall_test.py 实测选定（12/12 术语 recall@30 = 100%）：
#    stemmer(german) 归并德语屈折（Probemobilisierung/Probemobilisierungen），
#    其 German2 变体自带 ae/oe/ue→a/o/u，连 ASCII 转写也一并解决。
#    切勿删除或更改 —— analyzer 建表后不可修改，改只能删表重建。
ANALYZER = {"tokenizer": "icu",
            "filter": ["lowercase", "asciifolding", "removepunct",
                       {"type": "stemmer", "language": "german"}]}

SCALAR_STR = ["title", "chapter_title", "source_type", "language", "stance", "period",
              "doc_number", "doc_date", "doc_section"]
SCALAR_INT = ["chunk_index", "page_num", "doc_part"]
ARRAYS = ["region", "subfield"]


def build_schema(MilvusClient, DataType, Function, FunctionType):
    s = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
    s.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=512)
    s.add_field("dense", DataType.FLOAT_VECTOR, dim=DIM)
    s.add_field("text", DataType.VARCHAR, max_length=65535,
                enable_analyzer=True, analyzer_params=ANALYZER)
    s.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    s.add_field("title", DataType.VARCHAR, max_length=512)
    s.add_field("chunk_index", DataType.INT64)
    s.add_field("page_num", DataType.INT64, nullable=True)
    s.add_field("chapter_title", DataType.VARCHAR, max_length=1024, nullable=True)
    s.add_field("source_type", DataType.VARCHAR, max_length=32)
    s.add_field("language", DataType.VARCHAR, max_length=32)
    s.add_field("stance", DataType.VARCHAR, max_length=32)
    s.add_field("period", DataType.VARCHAR, max_length=32)
    s.add_field("region", DataType.ARRAY, element_type=DataType.VARCHAR,
                max_capacity=32, max_length=64)
    s.add_field("subfield", DataType.ARRAY, element_type=DataType.VARCHAR,
                max_capacity=16, max_length=64)
    s.add_field("doc_number", DataType.VARCHAR, max_length=32, nullable=True)
    s.add_field("doc_date", DataType.VARCHAR, max_length=32, nullable=True)
    s.add_field("doc_section", DataType.VARCHAR, max_length=64, nullable=True)
    s.add_field("doc_part", DataType.INT64, nullable=True)
    s.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                            input_field_names=["text"], output_field_names=["sparse"]))
    return s


def build_index(MilvusClient):
    ip = MilvusClient.prepare_index_params()
    ip.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="L2")
    ip.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
                 params={"inverted_index_algo": "DAAT_MAXSCORE",
                         "bm25_k1": 1.2, "bm25_b": 0.75})
    # 标量索引：基数都 < 500，用 BITMAP；范围过滤用 STL_SORT
    for f in ["source_type", "language", "stance", "title", "region", "subfield"]:
        ip.add_index(field_name=f, index_type="BITMAP")
    for f in ["page_num", "chunk_index"]:
        ip.add_index(field_name=f, index_type="STL_SORT")
    return ip


def to_row(cid, emb, doc, meta):
    row = {"chunk_id": cid, "dense": emb.tolist(), "text": doc or ""}
    for k in SCALAR_STR:
        v = meta.get(k)
        row[k] = v if isinstance(v, str) and v else None
    for k in SCALAR_INT:
        v = meta.get(k)
        row[k] = int(v) if isinstance(v, (int, float)) else None
    for k in ARRAYS:
        v = meta.get(k)
        row[k] = list(v) if isinstance(v, (list, tuple)) else []
    # ★ 不要提供 sparse —— 由 BM25 Function 自动生成
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="先删掉同名集合再重建")
    ap.add_argument("--limit", type=int, default=0, help="只灌前 N 条（调试用）")
    args = ap.parse_args()

    if not URI or not TOKEN:
        print("缺少 ZILLIZ_URI / ZILLIZ_TOKEN")
        return 2

    from pymilvus import MilvusClient, DataType, Function, FunctionType
    import corpus_lib as C

    print("=" * 80)
    print("生产迁移：本地 Chroma → Zilliz Cloud")
    print("=" * 80)
    cli = MilvusClient(uri=URI, token=TOKEN)

    if cli.has_collection(NAME):
        if not args.drop:
            print("目标集合已存在。如需重建请加 --drop；当前将做续传。")
        else:
            print("删除已存在的同名集合 ...", flush=True)
            t0 = time.time()
            cli.drop_collection(NAME)
            print("  已删除（%.1fs）" % (time.time() - t0))

    if not cli.has_collection(NAME):
        t0 = time.time()
        cli.create_collection(NAME, schema=build_schema(MilvusClient, DataType, Function, FunctionType),
                              index_params=build_index(MilvusClient))
        print("建集合 + 索引完成（%.1fs）" % (time.time() - t0))

    col = C.get_collection()
    total = col.count()
    if args.limit:
        total = min(total, args.limit)
    print("本地源库 %d 条，计划灌入 %d 条" % (col.count(), total))

    have = set()
    if not args.drop:
        try:
            r = cli.query(NAME, filter="", output_fields=["chunk_id"], limit=16384)
            have = {x["chunk_id"] for x in r}
            if have:
                print("目标库已有 %d 条，将跳过" % len(have))
        except Exception:
            pass

    t0 = time.time()
    n = 0
    off = 0
    while off < total:
        want = min(BATCH, total - off)
        r = col.get(limit=want, offset=off, include=["embeddings", "documents", "metadatas"])
        if not r["ids"]:
            break
        embs = r["embeddings"].astype(np.float32)      # ★ Chroma 返回 float64，必须转 float32
        rows = [to_row(cid, e, d, m)
                for cid, e, d, m in zip(r["ids"], embs, r["documents"], r["metadatas"])
                if cid not in have]
        if rows:
            cli.insert(NAME, rows)
            n += len(rows)
        off += len(r["ids"])
        if (off // BATCH) % 20 == 0:
            el = time.time() - t0
            print("  %6d/%d  %.0fs  (%.0f 条/秒)" % (off, total, el, off / max(el, 1e-9)), flush=True)

    print("  等待服务端索引 ...", flush=True)
    cli.flush(NAME)
    got = cli.query(NAME, filter="", output_fields=["count(*)"])[0].get("count(*)")
    el = time.time() - t0
    print()
    print("灌入 %d 条，耗时 %.0fs（%.0f 条/秒）" % (n, el, n / max(el, 1e-9)))
    print("服务端 count = %s" % got)
    if int(got) == col.count():
        print("✅ 行数与源库一致（%d）" % col.count())
    else:
        print("⚠️ 行数不一致：服务端 %s vs 源库 %d" % (got, col.count()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
