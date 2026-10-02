"""
适配器写入路径验证（用独立临时集合，跑完自动删除）
=================================================
验证 MilvusCollection 的 add / get / delete / upsert 在真实集群上可用，
覆盖项目里实际用到的写入模式：
  · ingest.py        : collection.add(...) / collection.delete(ids=[...])
  · ingest_new.py    : collection.delete(where={"title":...}) 然后 add(...)
  · pages/2_文献库管理.py : 同上（重新入库 = 先删后加，且 chunk_id 会重叠）
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

from pymilvus import MilvusClient, DataType, Function, FunctionType
from milvus_backend import MilvusCollection
from migrate_to_zilliz import build_schema, build_index

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()
NAME = "habrag_writetest"
DIM = 1024
RES = []


def check(name, fn):
    try:
        note = fn()
        RES.append((name, "PASS", note or ""))
        print("  %-46s PASS  %s" % (name, note or ""))
    except Exception as e:
        RES.append((name, "FAIL", "%s: %s" % (type(e).__name__, str(e)[:120])))
        print("  %-46s FAIL  %s: %s" % (name, type(e).__name__, str(e)[:120]))


def v(seed):
    return [((seed + i) % 100) / 100.0 for i in range(DIM)]


def main():
    cli = MilvusClient(uri=URI, token=TOKEN)
    if cli.has_collection(NAME):
        print("清理同名残留集合 ...", flush=True)
        cli.drop_collection(NAME)
    cli.create_collection(NAME, schema=build_schema(MilvusClient, DataType, Function, FunctionType),
                          index_params=build_index(MilvusClient))
    print("临时集合 %s 已建\n" % NAME)

    mc = MilvusCollection(URI, TOKEN, NAME)

    # ---- 1. add ----
    def t1():
        r = mc.add(ids=["A::0", "A::1", "A::2"],
                   documents=["Zwischenzollinie Berlin", "Conrad Hötzendorf", "Ultimatum 1914"],
                   embeddings=[v(1), v(2), v(3)],
                   metadatas=[{"title": "A", "chunk_index": 0, "page_num": 1,
                               "source_type": "primary", "language": "德文",
                               "stance": "中立描述", "period": "1914", "region": ["塞尔维亚"],
                               "subfield": ["政治史"]},
                              {"title": "A", "chunk_index": 1, "page_num": 2,
                               "source_type": "primary", "language": "德文",
                               "stance": "中立描述", "period": "1914", "region": [],
                               "subfield": []},
                              {"title": "A", "chunk_index": 2, "page_num": 3,
                               "source_type": "secondary", "language": "英文",
                               "stance": "衰落论", "period": "1914", "region": ["全帝国"],
                               "subfield": ["军事史"]}])
        return str(r)
    check("1. add（3 条，含空数组与缺字段）", t1)

    def t2():
        cli.flush(NAME); time.sleep(1)
        n = mc.count()
        assert n == 3, "期望 3，实际 %s" % n
        return "count = %d" % n
    check("2. count", t2)

    def t3():
        r = mc.get(ids=["A::1"], include=["documents", "metadatas"])
        assert r["ids"] == ["A::1"], r["ids"]
        m = r["metadatas"][0]
        assert m["title"] == "A" and m["chunk_index"] == 1, m
        return "doc=%r" % r["documents"][0][:24]
    check("3. get(ids=[...])", t3)

    def t4():
        r = mc.get(where={"title": "A"}, include=["metadatas"])
        assert len(r["ids"]) == 3, len(r["ids"])
        return "%d 条" % len(r["ids"])
    check("4. get(where=title)", t4)

    def t5():
        r = mc.get(where={"$and": [{"title": "A"},
                                   {"chunk_index": {"$gte": 1}},
                                   {"chunk_index": {"$lte": 2}}]},
                   include=["metadatas"])
        assert len(r["ids"]) == 2, len(r["ids"])
        return "%d 条（$and + $gte/$lte）" % len(r["ids"])
    check("5. get($and + 范围)", t5)

    def t6():
        r = mc.get(where={"region": {"$contains": "塞尔维亚"}}, include=["metadatas"])
        assert len(r["ids"]) == 1, len(r["ids"])
        return "%d 条（数组 $contains）" % len(r["ids"])
    check("6. get(数组 $contains)", t6)

    def t7():
        r = mc.query(query_embeddings=[v(1)], n_results=3,
                     include=["documents", "metadatas", "distances"])
        assert len(r["ids"][0]) == 3
        return "top1=%r" % r["documents"][0][0][:24]
    check("7. query（向量检索）", t7)

    # ---- 8. 重新入库模式：delete(where) 后立刻 add 相同 id ----
    def t8():
        mc.delete(where={"title": "A"})
        time.sleep(1)
        n = mc.count()
        assert n == 0, "删除后 count 应为 0，实际 %s" % n
        mc.add(ids=["A::0", "A::1", "A::2"],
               documents=["reinserted 0", "reinserted 1", "reinserted 2"],
               embeddings=[v(9), v(9), v(9)],
               metadatas=[{"title": "A", "chunk_index": i, "page_num": 10 + i,
                           "source_type": "primary", "language": "德文",
                           "stance": "中立描述", "period": "1914", "region": ["全帝国"],
                           "subfield": ["政治史"]} for i in range(3)])
        cli.flush(NAME); time.sleep(1)
        n2 = mc.count()
        assert n2 == 3, "重插后应为 3，实际 %s" % n2
        r = mc.get(ids=["A::0"], include=["documents"])
        assert r["documents"][0] == "reinserted 0", r["documents"][0]
        return "删→同 id 重插 → count=%d，内容已更新" % n2
    check("8. ★ 重新入库（delete(where) + add 相同 id）", t8)

    def t9():
        mc.delete(ids=["A::1"])
        time.sleep(1)
        n = mc.count()
        assert n == 2, "应为 2，实际 %s" % n
        return "delete(ids) 后 count = %d" % n
    check("9. delete(ids=[...])（ingest.py 回滚用）", t9)

    def t10():
        mc.upsert(ids=["A::2"], documents=["upserted"],
                  embeddings=[v(5)],
                  metadatas=[{"title": "A", "chunk_index": 2, "page_num": 99,
                              "source_type": "secondary", "language": "英文",
                              "stance": "衰落论", "period": "1914", "region": ["全帝国"],
                              "subfield": ["军事史"]}])
        time.sleep(1)
        r = mc.get(ids=["A::2"], include=["documents", "metadatas"])
        assert r["documents"][0] == "upserted", r["documents"][0]
        assert r["metadatas"][0]["page_num"] == 99
        return "upsert 生效"
    check("10. upsert", t10)

    def t11():
        r = mc.get(where={"title": "A"}, include=["metadatas"], limit=1)
        assert len(r["ids"]) == 1, len(r["ids"])
        return "limit=1 -> %d 条" % len(r["ids"])
    check("11. get(limit=)（app.py 的 limit=5000 路径）", t11)

    def t12():
        r = mc.get(include=[])
        assert len(r["ids"]) == 2, len(r["ids"])
        return "全表扫 get(include=[]) -> %d 条（get_book_counts 路径）" % len(r["ids"])
    check("12. get(include=[]) 全表扫", t12)

    # ---- 清理 ----
    print()
    t0 = time.time()
    cli.drop_collection(NAME)
    print("  临时集合已删除（%.1fs）；现有集合: %s" % (time.time() - t0, cli.list_collections() or "（空）"))

    npass = sum(1 for r in RES if r[1] == "PASS")
    print("\n" + "=" * 70)
    print("通过 %d / 失败 %d" % (npass, len(RES) - npass))
    for n, s, note in RES:
        if s == "FAIL":
            print("  ❌ %s -> %s" % (n, note))
    print("=" * 70)
    return 0 if npass == len(RES) else 1


if __name__ == "__main__":
    code = 3
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        try:
            _c = MilvusClient(uri=URI, token=TOKEN)
            if _c.has_collection(NAME):
                print("\n[兜底] 删除残留集合 ...", flush=True)
                _c.drop_collection(NAME)
                print("[兜底] 现有集合:", _c.list_collections() or "（空）")
        except Exception as e:
            print("[兜底] 清理失败:", e)
    sys.exit(code)
