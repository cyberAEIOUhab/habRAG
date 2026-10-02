"""
小规模真实召回验证（v2）
========================
目的：在真实语料上验证「BM25 词元匹配」能否替代本地「FTS5 trigram 子串匹配」。

v2 修正了三个 v1 的缺陷：
  1. v1 的本地基线恒为 0% —— fts.close() 写在函数定义之后、调用之前，异常被 except 吞掉
  2. v1 的真值集用 SQL LIKE（区分变音符）—— 导致 BM25 靠 asciifolding 找到的
     Szögyény/Bogićević 反倒被判为未命中
  3. v1 样本选取只用了单一拼写 —— 变体拼写的 chunk 可能没进样本

v2 的真值定义：文本与查询词**两侧都折叠变音符**后做子串匹配。
这样两条腿面对同一套真值，比较才是公平的。

安全：独立集合 habrag_recalltest，try/finally 保证跑完必 drop。
"""
import os
import re
import sys
import time
import sqlite3
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(_HERE, "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)
os.chdir(_HERE)
sys.path.insert(0, _HERE)

import numpy as np

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()
NAME = "habrag_recalltest"
DIM = 1024
N_BG = 26000
BATCH = 500
TOPK = 30

# (规范名, [需要纳入样本的拼写变体])
TERMS = [
    ("Zwischenzollinie",   ["Zwischenzollinie"]),
    ("Probemobilisierung", ["Probemobilisierung"]),
    ("Szogyeny",           ["Szogyeny", "Szögyény"]),
    ("Bogicevic",          ["Bogicevic", "Bogićević"]),
    ("Czernin",            ["Czernin"]),
    ("Hötzendorf",         ["Hötzendorf", "Hotzendorf", "Hoetzendorf"]),
    ("Annexionskrise",     ["Annexionskrise"]),
    ("Teilungsvertrag",    ["Teilungsvertrag"]),
    ("Zwischenfall",       ["Zwischenfall"]),
    ("Kriegsministerium",  ["Kriegsministerium"]),
    ("Ausgleich",          ["Ausgleich"]),
    ("Ultimatum",          ["Ultimatum"]),
]
NUMS = ["10364", "0050", "0005"]
UMLAUT = [("Hoetzendorf", "Hötzendorf"), ("Szogyeny", "Szögyény"),
          ("Bogicevic", "Bogićević")]

ANALYZER = {"tokenizer": "icu",
            "filter": ["lowercase", "asciifolding", "removepunct",
                       {"type": "stemmer", "language": "german"}]}
SCALAR_STR = ["title", "chapter_title", "source_type", "language", "stance", "period",
              "doc_number", "doc_date", "doc_section"]
SCALAR_INT = ["chunk_index", "page_num", "doc_part"]
ARRAYS = ["region", "subfield"]


def fold(s):
    """去变音符 + 小写。与 Milvus 的 asciifolding 语义对齐（ö→o, ć→c, é→e）。"""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def main():
    if not URI or not TOKEN:
        print("缺少 ZILLIZ_URI / ZILLIZ_TOKEN")
        return 2

    from pymilvus import MilvusClient, DataType, Function, FunctionType

    print("=" * 88)
    print("小规模真实召回验证 v2")
    print("=" * 88)

    # ---------------- Phase 1: 选样本 ----------------
    print("\n[Phase 1] 选取样本")
    con = sqlite3.connect("file:" + os.path.join(_HERE, "db", "chroma.sqlite3") + "?mode=ro",
                          uri=True, timeout=60)

    def like_ids(spellings):
        out = set()
        for sp in spellings:
            out |= {r[0] for r in con.execute(
                "SELECT e.embedding_id FROM embedding_fulltext_search f "
                "JOIN embeddings e ON e.id = f.rowid WHERE f.string_value LIKE ?",
                ("%" + sp + "%",))}
        return out

    hit = set()
    for _canon, spellings in TERMS:
        hit |= like_ids(spellings)
    for n in NUMS:
        hit |= like_ids([n])
    all_ids = [r[0] for r in con.execute("SELECT embedding_id FROM embeddings ORDER BY id")]
    con.close()
    print("  全库 %d 条；含基准词的（含变体拼写）%d 条" % (len(all_ids), len(hit)))

    step = max(1, len(all_ids) // N_BG)
    bg = set(all_ids[::step])
    sample = sorted(hit | bg)
    print("  背景样本 %d 条 → 合计样本 %d 条" % (len(bg), len(sample)))

    # ---------------- Phase 2: 读文本、定真值、建本地基线 ----------------
    print("\n[Phase 2] 读取样本 + 本地 FTS5 trigram 基线（同一份样本）")
    import corpus_lib as C
    col = C.get_collection()
    t0 = time.time()
    docs, metas, embs = {}, {}, {}
    for i in range(0, len(sample), BATCH):
        r = col.get(ids=sample[i:i + BATCH], include=["embeddings", "documents", "metadatas"])
        for cid, d, m, e in zip(r["ids"], r["documents"], r["metadatas"], r["embeddings"]):
            docs[cid] = d or ""
            metas[cid] = m
            embs[cid] = np.asarray(e, dtype=np.float32)
    print("  读到 %d 条，耗时 %.0fs" % (len(docs), time.time() - t0))

    # 真值：两侧折叠变音符后子串匹配
    folded = {cid: fold(txt) for cid, txt in docs.items()}
    truth = {}
    for canon, spellings in TERMS:
        f = fold(canon)
        truth[canon] = {c for c, t in folded.items() if f in t}
    for n in NUMS:
        truth[n] = {c for c, t in folded.items() if n in t}

    tmp = os.path.join(_HERE, "_recall_fts.sqlite3")
    if os.path.exists(tmp):
        os.remove(tmp)
    fts = sqlite3.connect(tmp)
    fts.execute("CREATE VIRTUAL TABLE t USING fts5(cid UNINDEXED, x, tokenize='trigram')")
    fts.executemany("INSERT INTO t(cid, x) VALUES (?, ?)", [(c, docs[c]) for c in sample])
    fts.commit()
    fts.execute("INSERT INTO t(t) VALUES('optimize')")
    fts.commit()
    print("  本地样本索引 %.1f MB" % (os.path.getsize(tmp) / 1048576))

    def local_ft(term, k=TOPK):
        """本地 FTS5 全文腿（生产代码同款：语法清洗 + ORDER BY rank）"""
        q = re.sub(r"[^\w]+", " ", term).strip()
        if not q:
            return []
        try:
            return [r[0] for r in fts.execute(
                "SELECT cid FROM t WHERE t MATCH ? ORDER BY rank LIMIT ?", (q, k)).fetchall()]
        except Exception as e:
            print("      [本地腿报错] %s: %s" % (type(e).__name__, e))
            return []

    # ---------------- Phase 3: 灌入 Zilliz ----------------
    print("\n[Phase 3] 建集合并灌入 Zilliz")
    cli = MilvusClient(uri=URI, token=TOKEN)

    def build_index():
        ip = MilvusClient.prepare_index_params()
        ip.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="L2")
        ip.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
                     params={"inverted_index_algo": "DAAT_MAXSCORE",
                             "bm25_k1": 1.2, "bm25_b": 0.75})
        ip.add_index(field_name="source_type", index_type="BITMAP")
        ip.add_index(field_name="title", index_type="BITMAP")
        ip.add_index(field_name="region", index_type="BITMAP")
        return ip

    if cli.has_collection(NAME):
        print("  发现同名残留，先删除 ...", flush=True)
        cli.drop_collection(NAME)

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

    t0 = time.time()
    cli.create_collection(NAME, schema=s, index_params=build_index())
    print("  建集合 %.1fs" % (time.time() - t0))

    def to_row(cid):
        m = metas[cid]
        row = {"chunk_id": cid, "dense": embs[cid].tolist(), "text": docs[cid]}
        for k in SCALAR_STR:
            v = m.get(k)
            row[k] = v if isinstance(v, str) and v else None
        for k in SCALAR_INT:
            v = m.get(k)
            row[k] = int(v) if isinstance(v, (int, float)) else None
        for k in ARRAYS:
            v = m.get(k)
            row[k] = list(v) if isinstance(v, (list, tuple)) else []
        return row

    t0 = time.time()
    for i in range(0, len(sample), BATCH):
        cli.insert(NAME, [to_row(c) for c in sample[i:i + BATCH]])
    cli.flush(NAME)
    dt = time.time() - t0
    n = cli.query(NAME, filter="", output_fields=["count(*)"])[0].get("count(*)")
    print("  灌入完成：count = %s，%.0fs（%.0f 条/秒）" % (n, dt, len(sample) / dt))

    def milvus_leg(field, data, k=TOPK):
        h = cli.search(NAME, data=data, anns_field=field,
                       search_params={"metric_type": "BM25" if field == "sparse" else "L2"},
                       limit=k, output_fields=["chunk_id"])
        # pymilvus 2.6 命中对象是 dict-like，主键在顶层；没有 h["id"]
        return [x["chunk_id"] for x in h[0]]

    def rec(got, ts):
        d = min(len(ts), TOPK)
        return None if d == 0 else len(set(got) & ts) / d

    # ---------------- Phase 4: 三方对比 ----------------
    print("\n[Phase 4] 召回对比（recall@%d，同一份样本与同一套真值）" % TOPK)
    print("  真值 = 两侧折叠变音符后做子串匹配（对 FTS5 与 BM25 公平）")
    print()
    print("  %-22s %7s %11s %11s %11s" % ("查询词", "真值数", "本地FTS5", "Milvus-BM25", "Milvus-稠密"))
    print("  " + "-" * 70)
    agg = {"local": [], "bm25": [], "dense": []}
    detail = []
    for canon, _sp in TERMS:
        ts = truth[canon]
        if not ts:
            print("  %-22s %7d   （样本中无此词）" % (canon, 0))
            continue
        lc = rec(local_ft(canon), ts)
        bm = rec(milvus_leg("sparse", [canon]), ts)
        dn = rec(milvus_leg("dense", [C.embed_text(canon)]), ts)
        agg["local"].append(lc)
        agg["bm25"].append(bm)
        agg["dense"].append(dn)
        detail.append((canon, len(ts), lc, bm, dn))
        print("  %-22s %7d %10.0f%% %10.0f%% %10.0f%%" % (canon, len(ts), lc * 100, bm * 100, dn * 100))
    print("  " + "-" * 70)
    print("  %-22s %7s %10.1f%% %10.1f%% %10.1f%%" % (
        "平均 recall@%d" % TOPK, "",
        np.mean(agg["local"]) * 100, np.mean(agg["bm25"]) * 100, np.mean(agg["dense"]) * 100))

    # ---------------- Phase 5: 档案号 ----------------
    print("\n[Phase 5] 档案号查询")
    print("  %-12s %8s %11s %11s" % ("档案号", "真值数", "本地FTS5", "Milvus-BM25"))
    print("  " + "-" * 46)
    for num in NUMS:
        ts = truth[num]
        if not ts:
            continue
        print("  %-12s %8d %10.0f%% %10.0f%%" % (
            num, len(ts), rec(local_ft(num), ts) * 100, rec(milvus_leg("sparse", [num]), ts) * 100))

    # ---------------- Phase 6: 德语变音符 ----------------
    print("\n[Phase 6] 德语变音符：ASCII 转写（oe/ue/ae）能否召回正确拼写")
    print("  %-14s %-14s %8s %10s %10s %12s" % ("ASCII 写法", "正确拼写", "真值数",
                                                "ASCII直查", "正确拼写", "展开变体后"))
    print("  " + "-" * 76)
    for ascii_form, correct in UMLAUT:
        ts = truth.get(correct) or {c for c, t in folded.items() if fold(correct) in t}
        if not ts:
            print("  %-14s %-14s %8s   （样本中无此词）" % (ascii_form, correct, "-"))
            continue
        raw = rec(milvus_leg("sparse", [ascii_form]), ts)
        ok = rec(milvus_leg("sparse", [correct]), ts)
        variant = ascii_form
        for pat, rep in [(r"oe", "o"), (r"ue", "u"), (r"ae", "a")]:
            variant = re.sub(pat, rep, variant, flags=re.I)
        var = rec(milvus_leg("sparse", [variant]), ts) if variant != ascii_form else None
        print("  %-14s %-14s %8d %9.0f%% %9.0f%% %11s" % (
            ascii_form, correct, len(ts), raw * 100, ok * 100,
            "—" if var is None else "%.0f%% (%s)" % (var * 100, variant)))

    # ---------------- Phase 7: 清理 ----------------
    print("\n[Phase 7] 清理")
    try:
        fts.close()
    except Exception:
        pass
    if os.path.exists(tmp):
        os.remove(tmp)
        print("  本地临时索引已删除")
    t0 = time.time()
    cli.drop_collection(NAME)
    print("  drop_collection %.1fs" % (time.time() - t0), flush=True)
    print("  集群现有集合：%s" % (cli.list_collections() or "（空）"))

    print("\n" + "=" * 88)
    print("判定：BM25 稀疏腿平均 recall@30 = %.1f%%（判定线 95%%，本地基线 %.1f%%）"
          % (np.mean(agg["bm25"]) * 100, np.mean(agg["local"]) * 100))
    print("=" * 88)
    return 0


if __name__ == "__main__":
    code = 3
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        try:
            from pymilvus import MilvusClient
            _c = MilvusClient(uri=URI, token=TOKEN)
            if _c.has_collection(NAME):
                print("\n[兜底] 检测到残留集合，正在删除 ...", flush=True)
                _c.drop_collection(NAME)
                print("[兜底] 已删除。现有集合：", _c.list_collections() or "（空）")
        except Exception as e:
            print("[兜底] 清理失败:", e)
    sys.exit(code)
