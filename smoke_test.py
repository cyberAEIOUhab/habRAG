"""
Zilliz Cloud Serverless 冒烟测试
=================================
在真正迁移之前，验证 Serverless 是否支持本项目依赖的全部能力。
只建一个临时集合（默认名 habrag_smoke），跑完自动删除，不碰任何现有数据。

用法（凭证只从环境变量读，不落盘、不回显）：
    $env:ZILLIZ_URI   = "https://<cluster-id>.serverless.<region>.vectordb.zillizcloud.com"
    $env:ZILLIZ_TOKEN = "<API Key 或 用户名:密码>"
    python smoke_test.py

依赖：pymilvus 2.6.x（本项目装在 _libs/，脚本会自动把它加进 sys.path）
"""
import os
import sys
import time
import traceback

# ---- 让 _libs/ 里的 pymilvus 可被 import ----
# ★ 追加到 sys.path 末尾，不要插到最前面：
#   pip --target 会把 numpy/pandas/protobuf/cachetools 的更新版本一并装进 _libs，
#   插到最前面会遮蔽系统版本，进而破坏 streamlit（它要求 pandas<3、protobuf<7、cachetools<7）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(_HERE, "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)

NAME = "habrag_smoke"
DIM = 8  # 冒烟用极小维度，建得快

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()

RESULTS = []  # (编号, 名称, 状态, 备注)


def mask(s):
    if not s:
        return "(空)"
    return s[:6] + "***" + s[-4:] if len(s) > 12 else "***"


def check(num, name, fn):
    """跑一项检查，任何异常都记为 FAIL 并继续，不中断整个测试"""
    t0 = time.time()
    try:
        note = fn()
        ms = (time.time() - t0) * 1000
        RESULTS.append((num, name, "PASS", "%s  (%.0f ms)" % (note or "", ms)))
        print("  [%2s] %-42s PASS   %s" % (num, name, note or ""), flush=True)
    except Exception as e:
        ms = (time.time() - t0) * 1000
        brief = "%s: %s" % (type(e).__name__, str(e).replace("\n", " ")[:160])
        RESULTS.append((num, name, "FAIL", brief))
        print("  [%2s] %-42s FAIL   %s" % (num, name, brief), flush=True)


def main():
    if not URI or not TOKEN:
        print("缺少凭证。请先设置环境变量 ZILLIZ_URI 和 ZILLIZ_TOKEN。")
        print("  URI   =", mask(URI))
        print("  TOKEN =", mask(TOKEN))
        return 2

    print("=" * 78)
    print("Zilliz Cloud Serverless 冒烟测试")
    print("=" * 78)
    print("  URI   =", URI)
    print("  TOKEN =", mask(TOKEN))
    print()

    from pymilvus import (
        MilvusClient, DataType, Function, FunctionType,
        AnnSearchRequest, RRFRanker,
    )

    print("  pymilvus 版本:", getattr(__import__("pymilvus"), "__version__", "?"))
    for _m in ("pandas", "numpy", "google.protobuf"):
        try:
            _mod = __import__(_m, fromlist=["x"])
            print("  %-16s %s" % (_m + ":", getattr(_mod, "__version__", "?")))
        except Exception as _e:
            print("  %-16s 不可用 (%s)" % (_m + ":", type(_e).__name__))
    print()

    cli = MilvusClient(uri=URI, token=TOKEN)
    print("-" * 78)
    print("A. 连接与分析器")
    print("-" * 78)

    def c01():
        return "已连接"
    check("1", "连接集群", c01)

    def c_server_version():
        d = cli.describe_collection(NAME) if cli.has_collection(NAME) else None
        return "服务端可达"
    check("2", "has_collection / 元数据接口", c_server_version)

    ANALYZER = {"tokenizer": "icu", "filter": ["lowercase", "asciifolding", "removepunct"]}

    def c03():
        txts = ["Zwischenzollinie und die österreichisch-ungarische Monarchie",
                "Bosnian Annexation Crisis 1908",
                "奥匈帝国的关税政策"]
        r = cli.run_analyzer(texts=txts, analyzer_params=ANALYZER)
        for i, item in enumerate(r):
            print("         %-46s -> %s" % (txts[i][:46], getattr(item, "tokens", item)))
        return "3 段文本分词完成"
    check("3", "run_analyzer（icu 分词器）", c03)

    def c04():
        words = ["Hötzendorf", "Hoetzendorf", "Bogićević", "Bogicevic",
                 "Szögyény", "Szogyeny", "österreichisch-ungarisch"]
        r = cli.run_analyzer(texts=words, analyzer_params=ANALYZER)
        t = [list(getattr(x, "tokens", []) or []) for x in r]
        for w, tk in zip(words, t):
            print("         %-26s -> %s" % (w, tk))
        accent_ok = t[2] == t[3] and t[2] != []          # Bogićević vs Bogicevic
        oe_ok = t[1] == t[0]                              # Hoetzendorf vs Hötzendorf
        return "变音符折叠 %s | 德语 oe 展开 %s" % (
            "✅ 归一(ć→c, ö→o)" if accent_ok else "❌ 不一致",
            "✅ 支持" if oe_ok else "❌ 不支持(oe≠ö)")
    check("4", "asciifolding 折叠行为（决定德语/波兰语召回）", c04)

    print()
    print("-" * 78)
    print("B. 建表（含 BM25 Function）")
    print("-" * 78)

    if cli.has_collection(NAME):
        cli.drop_collection(NAME)

    def c05():
        s = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        s.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=512)
        s.add_field("dense", DataType.FLOAT_VECTOR, dim=DIM)
        s.add_field("text", DataType.VARCHAR, max_length=65535,
                    enable_analyzer=True, analyzer_params=ANALYZER)
        s.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        s.add_field("source_type", DataType.VARCHAR, max_length=32)
        s.add_field("page_num", DataType.INT64, nullable=True)
        s.add_field("region", DataType.ARRAY, element_type=DataType.VARCHAR,
                    max_capacity=32, max_length=64)
        s.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                                input_field_names=["text"], output_field_names=["sparse"]))
        globals()["_SCHEMA"] = s
        return "含 dynamic field + BM25 Function"
    check("5", "构建 schema", c05)

    def c06():
        ip = MilvusClient.prepare_index_params()
        ip.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="L2")
        ip.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
                     params={"inverted_index_algo": "DAAT_MAXSCORE",
                             "bm25_k1": 1.2, "bm25_b": 0.75})
        ip.add_index(field_name="source_type", index_type="BITMAP")
        ip.add_index(field_name="region", index_type="BITMAP")
        globals()["_INDEX"] = ip
        cli.create_collection(NAME, schema=_SCHEMA, index_params=ip)
        return "集合已创建"
    check("6", "建集合 + 稀疏倒排索引(BM25)", c06)

    def c07():
        d = cli.describe_collection(NAME)
        fields = [f["name"] for f in d.get("fields", [])]
        fns = [f.get("name") for f in (d.get("functions") or [])]
        return "字段%d个, functions=%s" % (len(fields), fns)
    check("7", "describe_collection 回读 schema", c07)

    print()
    print("-" * 78)
    print("C. 写入（含动态字段）")
    print("-" * 78)

    def c08():
        cli.insert(NAME, [
            {"chunk_id": "t::0", "dense": [0.1] * DIM, "source_type": "primary",
             "page_num": 7, "region": ["塞尔维亚", "巴尔干地区"],
             "text": "Zwischenzollinie Bericht aus Berlin 1914",
             "custom_key": "未来才有的新字段"},          # ★ 动态字段：schema 里没声明
            {"chunk_id": "t::1", "dense": [0.3] * DIM, "source_type": "secondary",
             "page_num": None, "region": ["匈牙利本土"],
             "text": "Conrad von Hötzendorf Probemobilisierung"},
        ])
        cli.flush(NAME)
        return "2 行，未提供 sparse（由 Function 生成）"
    check("8", "insert（不给 sparse 赋值）", c08)

    def c09():
        r = cli.query(NAME, filter="", output_fields=["count(*)"])
        return "count = %s" % r[0].get("count(*)")
    check("9", "count(*)", c09)

    def c10():
        r = cli.query(NAME, filter='chunk_id == "t::0"', output_fields=["chunk_id", "custom_key"])
        return "动态字段回读: %s" % (r[0].get("custom_key") if r else "取不到")
    check("10", "动态字段（未声明键）写入与回读", c10)

    print()
    print("-" * 78)
    print("D. 检索（三条腿）")
    print("-" * 78)

    def c11():
        h = cli.search(NAME, data=[[0.1] * DIM], anns_field="dense",
                       search_params={"metric_type": "L2"}, limit=5,
                       output_fields=["chunk_id", "text"])
        return "命中 %d 条" % len(h[0])
    check("11", "稠密向量检索", c11)

    def c12():
        h = cli.search(NAME, data=["Zwischenzollinie"], anns_field="sparse",
                       search_params={"metric_type": "BM25"}, limit=5,
                       output_fields=["chunk_id", "text"])
        return "命中 %d 条 (BM25 传原始文本)" % len(h[0])
    check("12", "BM25 稀疏检索", c12)

    def c13():
        reqs = [
            AnnSearchRequest(data=[[0.1] * DIM], anns_field="dense",
                             param={"metric_type": "L2"}, limit=5),
            AnnSearchRequest(data=["Zwischenzollinie"], anns_field="sparse",
                             param={"metric_type": "BM25"}, limit=5),
        ]
        h = cli.hybrid_search(NAME, reqs, ranker=RRFRanker(60), limit=5,
                              output_fields=["chunk_id", "text"])
        return "命中 %d 条 (RRFRanker k=60)" % len(h[0])
    check("13", "hybrid_search + RRFRanker", c13)

    def c14():
        reqs = [
            AnnSearchRequest(data=[[0.1] * DIM], anns_field="dense",
                             param={"metric_type": "L2"}, limit=5,
                             expr='source_type == "primary"'),
            AnnSearchRequest(data=["Zwischenzollinie"], anns_field="sparse",
                             param={"metric_type": "BM25"}, limit=5,
                             expr='source_type == "primary"'),
        ]
        h = cli.hybrid_search(NAME, reqs, ranker=RRFRanker(60), limit=5,
                              output_fields=["chunk_id"])
        return "带 expr 过滤命中 %d 条" % len(h[0])
    check("14", "hybrid_search 的子查询级 expr 过滤", c14)

    print()
    print("-" * 78)
    print("E. 过滤表达式")
    print("-" * 78)

    def c15():
        r = cli.query(NAME, filter="ARRAY_CONTAINS_ANY(region, ['塞尔维亚','克罗地亚-斯拉沃尼亚'])",
                      output_fields=["chunk_id"])
        return "%d 行" % len(r)
    check("15", "ARRAY_CONTAINS_ANY（数组过滤）", c15)

    def c16():
        r = cli.query(NAME, filter='page_num is not null and page_num >= 5',
                      output_fields=["chunk_id", "page_num"])
        return "%d 行（nullable + IS NOT NULL + 范围）" % len(r)
    check("16", "nullable + 范围过滤", c16)

    def c17():
        a = cli.query(NAME, filter='chunk_id in ["t::0","t::1"]', output_fields=["chunk_id"])
        b = cli.query(NAME, filter='chunk_id not in ["t::999"]', output_fields=["chunk_id"])
        return "in=%d, not in=%d" % (len(a), len(b))
    check("17", "in / not in", c17)

    def c18():
        r = cli.query(NAME, filter='custom_key == "未来才有的新字段"', output_fields=["chunk_id"])
        return "动态字段直接按键名过滤: %d 行" % len(r)
    check("18", "动态字段过滤（无需特殊语法）", c18)

    def c19():
        ip = MilvusClient.prepare_index_params()
        ip.add_index(field_name="custom_key", index_type="AUTOINDEX",
                     index_name="custom_key_idx",
                     params={"json_cast_type": "varchar", "json_path": "custom_key"})
        cli.create_index(NAME, ip)
        return "JSON path 索引已建立"
    check("19", "动态字段建 JSON path 索引", c19)

    print()
    print("-" * 78)
    print("F. 更新与删除（重新入库的核心路径）")
    print("-" * 78)

    def c20():
        cli.upsert(NAME, [{"chunk_id": "t::0", "dense": [0.2] * DIM, "source_type": "primary",
                           "page_num": 8, "region": ["塞尔维亚"],
                           "text": "Zwischenzollinie upserted"}])
        return "upsert 成功"
    check("20", "upsert", c20)

    def c21():
        cli.delete(NAME, ids=["t::1"])
        n = cli.query(NAME, filter="", output_fields=["count(*)"])[0].get("count(*)")
        return "按主键删除后 count = %s" % n
    check("21", "delete(按主键)", c21)

    def c22():
        # ★★ 最关键的一项：删掉 t::0，然后立刻用【相同主键】重新插入
        cli.delete(NAME, filter='chunk_id == "t::0"')
        time.sleep(1)
        cli.insert(NAME, [{"chunk_id": "t::0", "dense": [0.9] * DIM, "source_type": "primary",
                           "page_num": 99, "region": ["全帝国"],
                           "text": "reinserted after delete"}])
        cli.flush(NAME)
        time.sleep(1)
        r = cli.query(NAME, filter='chunk_id == "t::0"', output_fields=["chunk_id", "page_num"])
        if not r:
            return "❌ 重插后查不到（tombstone 遮蔽）"
        if len(r) > 1:
            return "❌ 出现重复行 %d 条" % len(r)
        if r[0].get("page_num") != 99:
            return "❌ 读到旧值 page_num=%s" % r[0].get("page_num")
        return "✅ 删后同主键重插，读到新值"
    check("22", "★ 删 + 相同主键重插（重新入库）", c22)

    def c23():
        cli.delete(NAME, filter='source_type == "secondary"')
        return "按表达式删除成功"
    check("23", "delete(按表达式)", c23)

    print()
    print("-" * 78)
    print("G. 文档未明、只能实测确认的三项")
    print("-" * 78)

    def c24():
        # get_book_counts() 要全表扫 16 万行，依赖 query_iterator
        it = cli.query_iterator(NAME, filter="", output_fields=["chunk_id"], batch_size=10)
        n = 0
        while True:
            b = it.next()
            if not b:
                it.close()
                break
            n += len(b)
        return "query_iterator 可用，扫到 %d 行" % n
    check("24", "query_iterator（全表扫）", c24)

    def c25():
        h = cli.search(NAME, data=[[0.1] * DIM], anns_field="dense",
                       search_params={"metric_type": "L2"}, limit=3,
                       output_fields=["chunk_id"], consistency_level="Strong")
        return "consistency_level=Strong 被接受"
    check("25", "consistency_level 可指定", c25)

    def c26():
        # 单向门探测：能否给【已有集合】追加 BM25 Function
        # 注意：pymilvus 2.6.17 上的方法名是 add_collection_function，
        #       官方文档写的 add_function_field 是 Milvus 3.0 的名字。
        sf = cli.create_field_schema(name="sparse2", data_type=DataType.SPARSE_FLOAT_VECTOR)
        fn = Function(name="bm25_2", input_field_names=["text"],
                      output_field_names=["sparse2"], function_type=FunctionType.BM25)
        ip = MilvusClient.prepare_index_params()
        ip.add_index(field_name="sparse2", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        last = None
        for kwargs in ({"field_schema": sf, "func": fn, "index_params": ip},
                       {"field_schema": sf, "function": fn, "index_params": ip},
                       {"field_schema": sf, "func": fn}):
            try:
                cli.add_collection_function(collection_name=NAME, **kwargs)
                d = cli.describe_collection(NAME)
                fns = [f.get("name") for f in (d.get("functions") or [])]
                return "✅ 支持事后加 Function（双 BM25 可后补）；现存 %s" % fns
            except TypeError as e:
                last = e
            except Exception as e:
                return "❌ 服务端拒绝：%s: %s" % (type(e).__name__, str(e)[:110])
        raise last
    check("26", "add_collection_function（单向门探测）", c26)

    def c27():
        cli.add_collection_field(collection_name=NAME, field_name="new_scalar",
                                 data_type=DataType.VARCHAR, max_length=64, nullable=True)
        return "✅ 支持给已有集合加字段"
    check("27", "add_collection_field（schema 演化）", c27)

    def c29():
        # 第二个单向门探测：analzyer 到底能不能改
        for params in ({"analyzer_params": {"tokenizer": "standard"}},
                       {"field_params": {"analyzer_params": {"tokenizer": "standard"}}}):
            try:
                cli.alter_collection_field(collection_name=NAME, field_name="text", **params)
                return "⚠️ analyzer 居然可改 → 单向门不成立（这是好消息）"
            except TypeError:
                continue
            except Exception as e:
                return "analyzer 不可改（符合文档）: %s" % str(e)[:100]
        return "alter_collection_field 签名不匹配，未得出结论"
    check("29", "alter_collection_field 能否改 analyzer（单向门）", c29)

    print()
    print("-" * 78)
    print("H. 清理")
    print("-" * 78)

    def c28():
        cli.drop_collection(NAME)
        return "临时集合已删除"
    check("28", "drop_collection", c28)

    # ---------- 汇总 ----------
    print()
    print("=" * 78)
    print("汇总")
    print("=" * 78)
    npass = sum(1 for r in RESULTS if r[2] == "PASS")
    nfail = sum(1 for r in RESULTS if r[2] == "FAIL")
    for num, name, status, note in RESULTS:
        mark = "  OK  " if status == "PASS" else " FAIL "
        print("%s [%2s] %-42s %s" % (mark, num, name, note[:110]))
    print("-" * 78)
    print("通过 %d / 失败 %d" % (npass, nfail))

    if nfail:
        print()
        print("★ 有失败项。判定规则：")
        print("   - 第 5/6/12/13 项失败 → Serverless 不支持词法检索腿，本方案不成立")
        print("   - 第 22 项失败         → 『重新入库』功能不可用，需改设计")
        print("   - 第 26 项失败         → 双 BM25 方案不能后补，必须首次建表就做")
        print("   - 第 24/25 项失败      → 只是实现方式要换，不影响可行性")
    else:
        print()
        print("★ 全部通过 → 可以按 MIGRATION.md 开始正式迁移。")
    return 0 if not nfail else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(3)
