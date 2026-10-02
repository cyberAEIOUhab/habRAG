"""
生产集合验证：Zilliz Cloud 上的 habsburg（160,475 条）
======================================================
在**真实生产集合**上验证：
  A. 后端切换是否生效
  B. 12 术语 + 3 档案号的 recall@30（针对全库真值，不是抽样）
  C. corpus_lib 的全部调用点
  D. app.py 的五个工具函数

真值定义：把全库 160,475 条正文与查询词**两侧都折叠变音符**后做子串匹配。
这保证 BM25（asciifolding+stemmer）与本地 FTS5（trigram 子串）面对同一套真值。

用法（凭证从环境变量读）：
    $env:ZILLIZ_URI   = "https://<cluster>.serverless.ali-cn-hangzhou.cloud.zilliz.com.cn"
    $env:ZILLIZ_TOKEN = "<api key>"
    python validate_zilliz.py

只读操作：不写入、不删除任何数据。
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

# ★ 必须在 import config 之前设置
os.environ["HABRAG_BACKEND"] = "zilliz"

import numpy as np

TERMS = ["Zwischenzollinie", "Probemobilisierung", "Szogyeny", "Bogicevic", "Czernin",
         "Hötzendorf", "Annexionskrise", "Teilungsvertrag", "Zwischenfall",
         "Kriegsministerium", "Ausgleich", "Ultimatum"]
NUMS = ["10364", "0050", "0005"]
TOPK = 30


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def main():
    t_all = time.time()
    import config
    print("=" * 84)
    print("生产集合验证")
    print("=" * 84)
    print("  BACKEND =", config.BACKEND)
    print("  URI     =", config.ZILLIZ_URI or "（空）")

    import corpus_lib as C
    if not C.using_milvus():
        print("  ❌ BACKEND 不是 zilliz，切换未生效"); return 1
    print("  using_milvus() =", C.using_milvus())

    # ---------------- A. 连接与规模 ----------------
    print("\n[A] 连接与规模")
    t0 = time.time()
    col = C.get_collection()
    n = col.count()
    print("  服务端 chunk 总数 = %d  (%.1fs)" % (n, time.time() - t0))
    if n != 160475:
        print("  ⚠️ 与源库 160,475 不一致")

    # ---------------- B. 真值（本地全库） ----------------
    print("\n[B] 计算全库真值（本地，折叠变音符后子串匹配）")
    t0 = time.time()
    con = sqlite3.connect("file:" + os.path.join(_HERE, "db", "chroma.sqlite3") + "?mode=ro",
                          uri=True, timeout=60)
    rows = con.execute("SELECT e.embedding_id, f.string_value "
                       "FROM embedding_fulltext_search f "
                       "JOIN embeddings e ON e.id = f.rowid").fetchall()
    con.close()
    print("  读到 %d 条正文  (%.1fs)" % (len(rows), time.time() - t0))
    t0 = time.time()
    folded = [(cid, fold(txt)) for cid, txt in rows]
    truth = {}
    for term in TERMS + NUMS:
        f = fold(term)
        truth[term] = {cid for cid, t in folded if f in t}
    print("  真值计算完成 (%.1fs)" % (time.time() - t0))

    # ---------------- C. 召回对比 ----------------
    print("\n[C] recall@%d（真值来自全库，非抽样）" % TOPK)
    print("  %-22s %9s %12s %12s" % ("查询词", "真值数", "Milvus-BM25", "Milvus-稠密"))
    print("  " + "-" * 60)

    def hits(field, data, k=TOPK):
        """sparse 收原始查询文本；dense 收单条向量"""
        h = col.search_sparse(data, limit=k) if field == "sparse" else col.search_dense(data, limit=k)
        return [x["chunk_id"] for x in h]

    def rec(got, ts):
        d = min(len(ts), TOPK)
        return None if d == 0 else len(set(got) & ts) / d

    bm_all, dn_all = [], []
    for term in TERMS:
        ts = truth[term]
        if not ts:
            print("  %-22s %9d   （全库无此词）" % (term, 0)); continue
        bm = rec(hits("sparse", term), ts)
        dn = rec(hits("dense", C.embed_text(term)), ts)
        bm_all.append(bm); dn_all.append(dn)
        print("  %-22s %9d %11.0f%% %11.0f%%" % (term, len(ts), bm * 100, dn * 100))
    print("  " + "-" * 60)
    print("  %-22s %9s %11.1f%% %11.1f%%" % ("平均", "", np.mean(bm_all) * 100, np.mean(dn_all) * 100))

    print("\n  档案号：")
    for num in NUMS:
        ts = truth[num]
        if ts:
            print("    %-10s 真值 %4d   BM25 %3.0f%%" % (num, len(ts), rec(hits("sparse", num), ts) * 100))

    verdict = "✅ 达标（判定线 95%）" if np.mean(bm_all) >= 0.95 else "❌ 未达标"
    print("\n  BM25 平均 recall@%d = %.1f%%  %s" % (TOPK, np.mean(bm_all) * 100, verdict))

    # ---------------- D. 端到端检索 ----------------
    print("\n[D] 端到端 search_chunks（生产集合）")
    for q in ["Zwischenzollinie", "ÖUA VIII, Nr. 10364", "Conrad von Hötzendorf"]:
        t0 = time.time()
        r = C.search_chunks(query=q, n_results=5, use_rerank=False, use_rewrite=False)
        print("  %-24s %d 条  %5.0f ms" % (q, len(r), (time.time() - t0) * 1000))
        for c in r[:2]:
            print("      %-42s [%s] %s" % (str(c.get("title"))[:42], c.get("source_type"),
                                           str(c.get("citation"))[:38]))

    print("\n  带元数据过滤（source_type=primary）：")
    t0 = time.time()
    r = C.search_chunks(query="Balkankrieg", n_results=5, source_type="primary",
                        use_rerank=False, use_rewrite=False)
    print("    %d 条  %5.0f ms   source_type 均为 primary: %s"
          % (len(r), (time.time() - t0) * 1000,
             all(c.get("source_type") == "primary" for c in r) if r else "N/A"))

    # ---------------- E. 全部调用点 ----------------
    print("\n[E] corpus_lib 调用点")
    r = C.search_chunks(query="Zwischenzollinie", n_results=3, use_rerank=False, use_rewrite=False)
    cid, title = r[0]["chunk_id"], r[0]["title"]
    g = C.get_chunks_by_ids([cid])
    print("  get_chunks_by_ids      -> %s" % ("命中 1 条" if g else "❌ 空"))
    t0 = time.time()
    fb = C.get_chunks_for_book(title)
    print("  get_chunks_for_book    -> %d 块  (%.1fs)" % (len(fb), time.time() - t0))
    print("  get_chapters_for_book  -> %d 个章节" % len(C.get_chapters_for_book(title)))
    t0 = time.time()
    bc = C.get_book_counts()
    print("  get_book_counts        -> %d 书目 / %d 块  (%.1fs)"
          % (len(bc), sum(bc.values()), time.time() - t0))
    if sum(bc.values()) != 160475:
        print("    ⚠️ 总块数与 160,475 不符")

    # ---------------- F. app.py 的工具函数 ----------------
    # app.py 是 Streamlit 脚本，在 Streamlit 上下文外 import 会打印 bare-mode 警告，
    # 也可能因环境问题失败；整段包在 try 里，不让它影响前面的结论。
    print("\n[F] app.py 工具函数")
    A = None
    try:
        import app as A
    except Exception as e:
        print("  ❌ import app 失败：%s: %s" % (type(e).__name__, str(e)[:120]))
        print("  （不影响 A–E 的结论）")
    if A is not None:
        try:
            t0 = time.time()
            d = A.tool_expand_chunk(cid, window=2)      # 返回 list，不是 dict
            cnt = len(d) if isinstance(d, (list, dict)) else "?"
            print("  tool_expand_chunk      -> %s 块  (%.0f ms)" % (cnt, (time.time() - t0) * 1000))
        except Exception as e:
            print("  tool_expand_chunk      -> ❌ %s: %s" % (type(e).__name__, str(e)[:90]))
        # 注意：tool_list_books_by_filter(region, subfield, stance, source_type) 没有 n_results
        for fn, kw in [("tool_get_book_info", {"title": title}),
                       ("tool_list_sources_on_topic", {"topic": "Balkankrise", "n_results": 5}),
                       ("tool_list_books_by_filter", {"region": "塞尔维亚"}),
                       ("tool_list_books_by_filter", {"source_type": "primary", "stance": "衰落论"})]:
            try:
                t0 = time.time()
                out = getattr(A, fn)(**kw)
                cnt = len(out) if isinstance(out, (list, dict)) else "?"
                print("  %-22s %-34s -> %s 项  (%.0f ms)"
                      % (fn, str(kw)[:34], cnt, (time.time() - t0) * 1000))
            except Exception as e:
                print("  %-22s %-34s -> ❌ %s: %s"
                      % (fn, str(kw)[:34], type(e).__name__, str(e)[:70]))

    print("\n" + "=" * 84)
    print("总耗时 %.0fs" % (time.time() - t_all))
    print("=" * 84)
    return 0 if np.mean(bm_all) >= 0.95 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(3)
