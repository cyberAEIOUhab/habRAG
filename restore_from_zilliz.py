"""
从 Zilliz 恢复指定书目到本地 Chroma（可逆操作的逆操作）
======================================================
背景：2026-10-01 误执行了 clean.py，删掉本地库中两本书共 2,090 个 chunk。
     云端（Zilliz）数据完整，本脚本把它们原样拷回本地。

注意：Chroma 的 metadata 不接受 None 值，也不接受空列表，
     所以从 Milvus 行重建 meta 时要剔除 None / 空列表。
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(_HERE, "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from pymilvus import MilvusClient
import chromadb

from config import CHROMA_DB_PATH
from milvus_backend import row_to_meta

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()
SRC = "habsburg"
COLLECTION = "habsburg"
OUT = ["chunk_id", "dense", "text", "title", "chunk_index", "page_num", "chapter_title",
       "source_type", "language", "stance", "period", "region", "subfield",
       "doc_number", "doc_date", "doc_section", "doc_part"]

TITLES = [
    "The Economics of World War I",
    "Paris 1919: Six Months that Changed the World",
]


def clean_meta(meta):
    """Chroma 只接受 str/int/float/bool 与非空列表；剔除 None 与空列表"""
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = [x for x in v if x not in (None, "")]
            if not v:
                continue
            out[k] = v
        elif isinstance(v, str) and v == "":
            out[k] = ""
        else:
            out[k] = v
    return out


def main():
    cli = MilvusClient(uri=URI, token=TOKEN)
    local = chromadb.PersistentClient(path=CHROMA_DB_PATH).get_or_create_collection(COLLECTION)
    before = local.count()
    print("本地库现有 %d 块" % before)

    total_added = 0
    PAGE = 200   # ★ 必须分页：一次性拉 1500 条带 1024 维向量会超过 gRPC 4MB 消息上限
    for title in TITLES:
        esc = title.replace("'", "\\'")
        rows, off = [], 0
        while True:
            b = cli.query(SRC, filter="title == '%s'" % esc, output_fields=OUT,
                          limit=PAGE, offset=off, consistency_level="Strong")
            if not b:
                break
            rows += b
            off += len(b)
            if len(b) < PAGE:
                break
        rows.sort(key=lambda r: r.get("chunk_index") or 0)
        print("\n《%s》从云端取回 %d 块" % (title, len(rows)))
        if not rows:
            continue

        t0 = time.time()
        B = 200
        for i in range(0, len(rows), B):
            chunk = rows[i:i + B]
            ids = [r["chunk_id"] for r in chunk]
            docs = [r.get("text", "") for r in chunk]
            embs = [r.get("dense") for r in chunk]
            metas = [clean_meta(row_to_meta(r)) for r in chunk]
            # 用 upsert 而非 add：重复运行不会因 id 已存在而报错
            local.upsert(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
            total_added += len(ids)
        print("  写回完成（%.1fs）" % (time.time() - t0))

    after = local.count()
    print("\n本地库现在 %d 块（恢复 %d 块）" % (after, total_added))
    if after == 160475:
        print("✅ 已回到 160,475，与 Zilliz 一致")
    else:
        print("⚠️ 期望 160,475，实际 %d（差 %d）" % (after, 160475 - after))

    # 逐本核对
    print("\n逐本核对：")
    for title in TITLES:
        n = len(local.get(where={"title": title}, include=[])["ids"])
        print("  《%s》 -> %d 块" % (title, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
