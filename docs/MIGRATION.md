# habRAG → Zilliz Cloud Serverless 迁移指南

**目标**：把本地 Chroma 的 160,475 个 chunk 迁到 Zilliz Cloud Serverless（阿里云华东1·杭州），全文腿由 FTS5 trigram 换成 BM25 稀疏向量。

**配套**：`docs/OPERATIONS.md`（运维与压测）、`docs/ARCHITECTURE.md`（项目全貌）、
`zilliz-serverless-调研报告.md` 与 `reports/milvus-2.6-pymilvus-research.md`（两份带 URL 的原始调研）。

---

## 摘要：三个反直觉的结论

| # | 结论 | 依据 |
|---|---|---|
| 1 | **`app.py` 零改动** | 写一个 ~150 行适配器让 Milvus 冒充 Chroma collection 的 `count/get/query`，`app.py` 的 5 处调用 + `corpus_lib` 的 4 处全部不用碰 |
| 2 | **不需要重新 embedding** | 本地向量直接导出，实测 **3,052 块/秒 → 全量 0.9 分钟** |
| 3 | **成本 ≈ ¥1.3/月** | 写入走 Import 是 **¥0**，读取在你这个频率下可忽略。注册赠 ¥300 券 |

**真正的工作量在三处**：Schema 设计、适配器、`search_chunks` 的两腿替换。

---

## 阶段 0：注册 + 冒烟测试（半天，¥0）—— 这一步不过，后面都别做

### 0.1 注册

1. 打开 https://cloud.zilliz.com.cn/signup
2. 用**企业邮箱**注册（赠 ¥300 券；若绑定云市场支付方式，有效期从 30 天延长到 1 年）
3. 需要：邮箱验证码 → 密码（8–128 位，含大小写+数字+特殊符）→ 手机号 → 短信验证码
   > ⚠️ **1 个手机号只能注册 1 个账号**

### 0.2 创建 Serverless 集群

1. 控制台 → 创建集群 → 选 **Serverless**
2. **地域只能选「华东1（杭州）」**——中国区 Serverless 没有第二个选项（腾讯云和 AWS 中国区都不支持 Serverless）
3. **创建过程中必须保存集群凭证（用户名+密码），只展示一次**
4. 状态变为「运行中」即成功

**取连接信息**：

| 项 | 位置 / 格式 |
|---|---|
| URI | 集群详情页「连接信息」卡片。格式 `https://{cluster-id}.serverless.{region}.vectordb.zillizcloud.com`，**不带端口**（那是 Dedicated 的 `:19530`） |
| Token | ① 组织 → API Keys 页创建 API 密钥（仅 Owner/Project Admin 可建）；② 或直接用 `用户名:密码` |

> 中国区的完整域名后缀（是否 `.com.cn`）官方没有明文，**以控制台显示为准**。

### 0.3 冒烟测试（关键）

`pip install pymilvus`，然后跑这个脚本。**15 项里只要有一项失败，就停下来重新评估方案**（改 Dedicated 或维持本地）。

```python
# smoke_test.py —— 在 Zilliz Serverless 上验证所有依赖的能力
from pymilvus import (MilvusClient, DataType, Function, FunctionType,
                      AnnSearchRequest, RRFRanker)

URI   = "https://<你的-cluster-id>.serverless.<region>.vectordb.zillizcloud.com"
TOKEN = "<你的 API Key 或 用户名:密码>"
NAME  = "smoke_test"

cli = MilvusClient(uri=URI, token=TOKEN)
print("[1] 连接成功")

# ---- 先测 analyzer（analyzer 建表即永久固定，改只能删表重建，必须先测）----
for txt in ["Zwischenzollinie und die österreichisch-ungarische Monarchie",
            "Bogićević Hötzendorf Szögyény",
            "奥匈帝国 的 关税 政策"]:
    r = cli.run_analyzer(text=txt, analyzer_params={
        "tokenizer": "icu",
        "filter": ["lowercase", "asciifolding", "removepunct",
                   {"type": "stemmer", "language": "german"}]})
    print("    tokens:", r[:12])

if cli.has_collection(NAME):
    cli.drop_collection(NAME)

schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=512)
schema.add_field("dense",    DataType.FLOAT_VECTOR, dim=8)          # 冒烟用 8 维
schema.add_field("text",     DataType.VARCHAR, max_length=65535, enable_analyzer=True)
schema.add_field("sparse",   DataType.SPARSE_FLOAT_VECTOR)
schema.add_field("source_type", DataType.VARCHAR, max_length=32)
schema.add_field("region",   DataType.ARRAY, element_type=DataType.VARCHAR,
                 max_capacity=32, max_length=64)
schema.add_field("page_num", DataType.INT64, nullable=True)
schema.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                             input_field_names=["text"], output_field_names=["sparse"]))
print("[2] schema + BM25 Function 通过")

idx = MilvusClient.prepare_index_params()
idx.add_index(field_name="dense",  index_type="AUTOINDEX", metric_type="L2")
idx.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
              params={"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75})
idx.add_index(field_name="source_type", index_type="BITMAP")
idx.add_index(field_name="region",      index_type="BITMAP")
cli.create_collection(NAME, schema=schema, index_params=idx)
print("[3] 建表 + 稀疏倒排索引 通过")

# 插入：不要给 sparse 赋值，由 Function 自动算
cli.insert(NAME, [{"chunk_id": "t::0", "dense": [0.1] * 8, "source_type": "primary",
                   "region": ["塞尔维亚", "巴尔干地区"], "page_num": 7,
                   "text": "Zwischenzollinie Bericht aus Berlin 1914"}])
cli.flush(NAME)
print("[4] insert（不给 sparse 赋值）通过；count =", cli.query(NAME, filter="",
      output_fields=["count(*)"])[0]["count(*)"])

# 三路验证
d = cli.search(NAME, data=[[0.1] * 8], anns_field="dense",
               search_params={"metric_type": "L2"}, limit=5,
               output_fields=["chunk_id", "text"])
print("[5] 稠密向量检索 通过")
s = cli.search(NAME, data=["Zwischenzollinie"], anns_field="sparse",
               search_params={"metric_type": "BM25"}, limit=5,
               output_fields=["chunk_id", "text"])
print("[6] BM25 稀疏检索（data 传原始文本）通过, hits =", len(s[0]))

reqs = [AnnSearchRequest(data=[[0.1] * 8], anns_field="dense",
                         param={"metric_type": "L2"}, limit=5),
        AnnSearchRequest(data=["Zwischenzollinie"], anns_field="sparse",
                         param={"metric_type": "BM25"}, limit=5)]
h = cli.hybrid_search(NAME, reqs, ranker=RRFRanker(60), limit=5,
                      output_fields=["chunk_id", "text"])
print("[7] hybrid_search + RRFRanker(k=60) 通过, hits =", len(h[0]))

f = cli.query(NAME, filter="ARRAY_CONTAINS_ANY(region, ['塞尔维亚','克罗地亚-斯拉沃尼亚'])",
              output_fields=["chunk_id"])
print("[8] ARRAY_CONTAINS_ANY 通过, rows =", len(f))
f = cli.query(NAME, filter="page_num is not null and page_num >= 5", output_fields=["chunk_id"])
print("[9] nullable + IS NOT NULL + 范围过滤 通过, rows =", len(f))
f = cli.query(NAME, filter="chunk_id in ['t::0']", output_fields=["chunk_id"])
print("[10] in 列表 通过, rows =", len(f))
f = cli.query(NAME, filter="chunk_id not in ['t::999']", output_fields=["chunk_id"])
print("[11] not in 通过, rows =", len(f))

cli.upsert(NAME, [{"chunk_id": "t::0", "dense": [0.2] * 8, "source_type": "primary",
                   "region": ["塞尔维亚"], "page_num": 8, "text": "upserted"}])
cli.delete(NAME, ids=["t::0"])
print("[12] upsert + delete(按主键) 通过")
cli.insert(NAME, [{"chunk_id": "t::1", "dense": [0.3] * 8, "source_type": "secondary",
                   "region": ["匈牙利本土"], "page_num": None, "text": "loeschen"}])
cli.flush(NAME)
cli.delete(NAME, filter="source_type == 'secondary'")
print("[13] delete(按表达式) 通过")

cli.drop_collection(NAME)
print("[14] drop_collection 通过")
print("\n全部通过 → 可以继续。有任何一项报错 → 停下，把报错原文发出来重新评估。")
```

### 0.4 冒烟测试的判定

| 结果 | 处置 |
|---|---|
| 全部 14 项通过 | 继续阶段 1 |
| BM25 Function 或 sparse 索引失败 | **停**。说明 Serverless 不支持词法检索腿 → 改 Dedicated（¥912/月）或维持本地 |
| `hybrid_search` 报 "only for dedicated" | 大概率是文档模板残留（见附录 A.6）。改用**客户端两腿融合**（阶段 5 的方案 B），功能等价 |
| `ARRAY_CONTAINS_ANY` 失败 | 可退化为 `region` 存成拼接字符串 + `json_contains`；会影响 `build_where` 的翻译 |

> ⚠️ **两个"单向门"，必须在建表前就定死：**
>
> **① analyzer 建表即永久固定**，改只能删表重建。所以 `run_analyzer()` 必须在建表**之前**跑。
>
> **② BM25 Function 的输入字段也必须在建表时定义。** 官方 `Alter Collection Schema` 里给已有集合加 Function 的工作流写着
> "currently documented for Zilliz Cloud **On-Demand Clusters**. This page does not establish... **Serving Cluster** availability"——
> Serverless 属于 Serving 集群。而且即使可用，官方也明确 "You cannot use an existing `TEXT` field as the BM25 input in this
> schema-change workflow"。
>
> **直接后果**：如果要走"双文本字段 + 双 BM25 Function"来解决德语 `ö↔oe`，**必须首次建表就做**，不能事后补。

### 0.5 ★ 冒烟测试实测结果（2026-10-01，29/29 全部通过）

集群：`in05-7fff4694e53214d.serverless.ali-cn-hangzhou.cloud.zilliz.com.cn`（Serverless-01，ali-cn-hangzhou）

**结论：方案成立，可以迁移。** 以下全部为实测，非文档推断。

#### 三项最关键的确认

| 结论 | 实测证据 |
|---|---|
| **`hybrid_search` + BM25 在 Serverless 上可用** | `hybrid_search(..., ranker=RRFRanker(60))` 正常返回。**附录 A.6 那条"仅限 Dedicated"的文档警告确认为误报** |
| **「重新入库」路径安全** | 删 `t::0` → 立刻用**相同主键**重插 → 查回 `page_num=99`（新值），无重复行、无 tombstone 遮蔽 |
| **BM25 Function 真的建起来了** | `describe_collection()` 返回 `functions=['bm25']`；插入时**不给 `sparse` 赋值**，由 Function 生成；BM25 检索传原始文本即可命中 |

#### analyzer 实测（`icu` + `lowercase` + `asciifolding` + `removepunct`）

```
Hötzendorf                -> hotzendorf        Hoetzendorf  -> hoetzendorf   ❌ 不匹配
Bogićević                 -> bogicevic         Bogicevic    -> bogicevic     ✅ 匹配
Szögyény                  -> szogyeny          Szogyeny     -> szogyeny      ✅ 匹配
österreichisch-ungarisch  -> osterreichisch, ungarisch                     连字符拆成两个词
奥匈帝国                   -> 奥, 匈, 帝国       （"的" 也成 token）         ⚠️ 中文按字切
```

- **`asciifolding` 把 `ć→c`、`ö→o`、`é→e` 全部归一** → 对现有语料是**净改善**：
  现在 FTS5 trigram 下 `Bogićević` 是 **0 条**、`Bogicevic` 是 257 条；迁移后两者等价。
- **德语 `oe` 展开仍然不支持**（`Hoetzendorf` ≠ `Hötzendorf`）——**但可以用查询侧展开零成本解决，不需要双 BM25**，见下。
- **中文分词很粗**（`奥匈帝国` → `奥`/`匈`/`帝国`，`的` 也进索引）。语料 72.4% 英文 + 26.0% 德文，可接受；中文查询靠稠密腿（bge-m3）+ A9 改写兜底。

#### ★ 德语 `oe/ue/ae` 的正解：查询侧展开，而非双 BM25

> **⚠️ 本节已被 0.6 节取代**：加上 `stemmer(german)` 后 `Hoetzendorf` 直查即达 100%，
> **不需要查询侧展开，也不需要双 BM25**。以下内容保留作为备选思路与原理说明。

实测的折叠行为给了答案：**`ö` 被折成 `o`，而不是 `oe`**。所以

```
语料 Hötzendorf  ->  索引为 hotzendorf
查询 Hoetzendorf ->  索引为 hoetzendorf   ❌ 对不上
```

但只要**在查询侧把 `oe/ue/ae` 也折成 `o/u/a`**，就能对上：

```
查询 Hoetzendorf -> 生成变体 Hotzendorf -> 索引为 hotzendorf  ✅ 命中
查询 Mueller     -> 生成变体 Muller     -> 索引为 muller      ✅ 命中 corpus 的 Müller
```

**实现**（加在 `corpus_lib` 的查询构造处，约 5 行）：

```python
import re
_UMLAUT_EXPAND = [(re.compile(r"oe", re.I), "o"), (re.compile(r"ue", re.I), "u"),
                  (re.compile(r"ae", re.I), "a")]

def umlaut_variants(q):
    """给德语 ASCII 转写（oe/ue/ae）生成折叠变体，配合 asciifolding(ö→o) 使用"""
    out = [q]
    v = q
    for pat, rep in _UMLAUT_EXPAND:
        v = pat.sub(rep, v)
    if v != q:
        out.append(v)
    return out
```

把返回的每条变体都作为一路 BM25 子查询（或直接并入 A9 改写出的查询列表）。

**为什么不需要双 BM25**：双 BM25 要占掉 Serverless 每集合 4 个向量字段中的 2 个，
多一条检索腿、多一份索引存储、还要在入库时生成归一化副本——而 `ß→ss`、`ö→o`、`ć→c`
这些 asciifolding 已经处理好了，**只剩 `oe/ue/ae` 三个二合字母需要在查询侧补**。

#### ★ 两个单向门：实测**都不可逆**（这是本次测试最重要的产出）

```
add_collection_function  -> MilvusException(code=1100,
    "currently does not support adding BM25 function: invalid parameter")

alter_collection_field   -> MilvusException(code=1100,
    "analyzer_params does not allow update in collection field param")
```

**含义：`analyzer` 与 `BM25 Function` 一旦建表就无法修改。**
若要走双 BM25 做德语归一化，**必须在首次建表时就把两个文本字段 + 两个 Function 一起定义**。
（另注：pymilvus 2.6.17 上的方法名是 `add_collection_function`，官方文档写的 `add_function_field` 是 Milvus 3.0 的名字。）

#### 其余全部通过

`enable_dynamic_field`（写入/回读/按键名过滤/建 JSON path 索引）、`add_collection_field`、
`ARRAY_CONTAINS_ANY`、nullable + `IS NOT NULL` + 范围、`in`/`not in`、`query_iterator`、
`consistency_level="Strong"`、`upsert`、`delete(ids)`、`delete(filter)`、`count(*)`。

#### ⚠️ 两个新增注意事项

**① 删除后有最终一致性延迟。** 两次相同流程的测试中，`delete(ids=["t::1"])` 之后立刻 `count(*)`
一次返回 1（正确）、一次返回 2（读到旧值）。**凡"删除后立即统计"的代码必须显式指定
`consistency_level="Strong"`**，否则会显示错误的数字。受影响的位置：
`pages/2_文献库管理.py:195-197`（删除后回显剩余 chunk 数）。

**② `drop_collection` 很慢：实测 48.3 秒。** 其余操作为毫秒级：

| 操作 | 实测耗时 |
|---|---|
| 建集合 + 稀疏索引 | 4.3 s |
| 插入 2 行 + flush | 0.9 s |
| `hybrid_search` | **58 ms** |
| 稠密检索（首次 / 后续） | 322 ms / ~60 ms |
| BM25 检索 | 104 ms |
| 建 JSON path 索引 | 1.8 s |
| 删 + 同主键重插 | 8.1 s |
| **`drop_collection`** | **48.3 s** |

**含义**：如果首次建表时 analyzer 选错、需要重建集合，销毁这一步就要等近 1 分钟。
这是"单向门"代价的具体数量级 —— 所以 Phase 1 值得多花时间验证。

### 0.6 ★★ 真实召回验证结果（2026-10-01）

**结论：BM25 稀疏腿 recall@30 = 100.0%，与本地 FTS5 trigram 基线完全持平。判定线 95%，实际 100%。**

测试设计（脚本见 `recall_test.py`）：

- 样本 32,983 条 = 全部含基准词的 7,430 条（含变体拼写） + 26,746 条等距背景样本
- **同一份样本上重建本地 FTS5 trigram 索引**作为基线，避免"样本变了"造成误判
- 真值 = 文本与查询词**两侧都折叠变音符**后做子串匹配（对两条腿公平）
- 三方对比：本地 FTS5 / Milvus BM25 稀疏腿 / Milvus 稠密腿

| 查询词 | 真值数 | 本地 FTS5 | **Milvus BM25** | 稠密腿 |
|---|---:|---:|---:|---:|
| Zwischenzollinie | 25 | 100% | **100%** | 40% |
| Probemobilisierung | 28 | 100% | **100%** | 7% |
| Szogyeny | 534 | 100% | **100%** | 57% |
| Bogicevic | 257 | 100% | **100%** | 100% |
| Czernin | 1353 | 100% | **100%** | 100% |
| Hötzendorf | 633 | 100% | **100%** | 83% |
| Annexionskrise | 140 | 100% | **100%** | 50% |
| Teilungsvertrag | 6 | 100% | **100%** | 33% |
| Zwischenfall | 191 | 100% | **100%** | 13% |
| Kriegsministerium | 1068 | 100% | **100%** | 80% |
| Ausgleich | 1621 | 100% | **100%** | 97% |
| Ultimatum | 2000 | 100% | **100%** | 100% |
| **平均** | | **100.0%** | **100.0%** | 63.4% |

档案号：`10364`(9) / `0050`(42) / `0005`(78) → 本地与 BM25 **均 100%**。

#### ★ 关键发现：`stemmer` 是必需的，且它同时解决了两个问题

第一轮（**无** stemmer）BM25 只有 **92.4%**，两个词明显掉队：

```
Probemobilisierung   真值 28，BM25 仅 46%
Teilungsvertrag      真值  6，BM25 仅 67%
```

排查后确认**不是"子串 vs 词元"的语义差异**，而是**德语屈折变化未被归并**：

```
Probemobilisierung   全库 28 篇命中 | 独立词 14 | 嵌在更长词里 15  ← 复数 Probemobilisierungen
Teilungsvertrag      全库  6 篇命中 | 独立词  4 | 嵌在更长词里  1  ← 属格 Teilungsvertrags
```

BM25 把 `Probemobilisierung` 和 `Probemobilisierungen` 当成两个不同词元，于是召回腰斩。

三种 analyzer 实测对比（10 组单复数配对）：

| 配置 | 屈折归一 | 副作用 |
|---|---|---|
| 无 stemmer | **0 / 10** | — |
| **`stemmer(german)`** | **10 / 10** | 对英文**保守**：`annexation`→`annexation` 不变，只归并 `annexations` |
| `stemmer(english)` | 7 / 10 | 英文**过度**词干化：`mobilization`→`mobil`、`annexation`→`annex`，增加词元碰撞；且漏掉德语 |

**加上 `stemmer(german)` 后，12/12 术语 + 3/3 档案号全部 100%。**

#### 意外收获：`oe/ue/ae` 也被一并解决了

Milvus 的 `stemmer(german)` 采用 German2 变体，自带 `ae/oe/ue → a/o/u` 预处理，所以：

```
Hoetzendorf（ASCII 转写）查 Hötzendorf（633 条真值）：
   无 stemmer  ->  13%
   有 stemmer  -> 100%   ✅
```

**因此 0.5 节里设计的查询侧 `umlaut_variants()` 展开方案已不需要，可以不做。**
（保留它也无害，作为额外保险。）

---

## 阶段 1：Schema 设计

字段类型与长度**全部来自对你库里实际数据的实测**，不是猜的。

```python
# schema_def.py
from pymilvus import MilvusClient, DataType, Function, FunctionType

COLLECTION = "habsburg"

# 语料实测：英文 72.4% / 德文 26.0% / 混合+波兰+中文 1.6%
# 混合语料官方推荐 icu；removepunct 是必需的（icu 会把标点留成独立 token）
# ★★ stemmer(german) 是实测选定的，不要删 —— 见 0.6 节：
#    没有它德语屈折无法归并（Probemobilisierung ≠ Probemobilisierungen），
#    recall@30 从 100% 掉到 92.4%；加上它 12/12 术语全部 100%。
#    German2 变体还自带 ae/oe/ue → a/o/u 预处理，连 ASCII 转写都一并解决。
#    它对英文是保守的（annexation→annexation 不变，只归并 annexations），
#    而 stemmer(english) 反而会过度词干化（mobilization→mobil）并漏掉德语，不要用。
ANALYZER = {
    "tokenizer": "icu",
    "filter": ["lowercase", "asciifolding", "removepunct",
               {"type": "stemmer", "language": "german"}],
}

def build_schema():
    # ★ enable_dynamic_field=True：未声明的键自动进隐藏 JSON 字段 $meta，
    #   这是"Chroma 无 schema"的逃生口——未来新素材引入新 metadata 键时不必改表。
    #   但高频字段仍须显式声明：官方明确说动态键 "not optimized for high-frequency
    #   retrieval"，且必须显式列进 output_fields 才会返回。
    s = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
    # —— 主键与向量 ——
    s.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=512)
    s.add_field("dense",    DataType.FLOAT_VECTOR, dim=1024)
    # —— 全文腿 ——
    s.add_field("text",   DataType.VARCHAR, max_length=65535,
                enable_analyzer=True, analyzer_params=ANALYZER)
    s.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    # —— 标量（原来 Chroma 的 metadata）——
    s.add_field("title",         DataType.VARCHAR, max_length=512)
    s.add_field("chunk_index",   DataType.INT64)
    s.add_field("page_num",      DataType.INT64,   nullable=True)
    s.add_field("chapter_title", DataType.VARCHAR, max_length=1024, nullable=True)
    s.add_field("source_type",   DataType.VARCHAR, max_length=32)
    s.add_field("language",      DataType.VARCHAR, max_length=32)
    s.add_field("stance",        DataType.VARCHAR, max_length=32)
    s.add_field("period",        DataType.VARCHAR, max_length=32)
    s.add_field("region",   DataType.ARRAY, element_type=DataType.VARCHAR,
                max_capacity=32, max_length=64)
    s.add_field("subfield", DataType.ARRAY, element_type=DataType.VARCHAR,
                max_capacity=16, max_length=64)
    s.add_field("doc_number",  DataType.VARCHAR, max_length=32, nullable=True)
    s.add_field("doc_date",    DataType.VARCHAR, max_length=32, nullable=True)
    s.add_field("doc_section", DataType.VARCHAR, max_length=64, nullable=True)
    s.add_field("doc_part",    DataType.INT64,   nullable=True)
    # —— 全文腿的生成器 ——
    s.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                            input_field_names=["text"], output_field_names=["sparse"]))
    return s
```

### 设计依据（实测数据）

| 字段 | 类型 | 实测依据 |
|---|---|---|
| `chunk_id` | VARCHAR(**512**) | 最长 189 字节（`title` 183 + `::` + 序号） |
| `text` | VARCHAR(**65535**) | 最长 **7,348 UTF-8 字节**；上限就是 65535，拉满即可（变长不预分配） |
| `title` | VARCHAR(512) | 190 种，最长 183 字节 |
| `chapter_title` | VARCHAR(1024), nullable | 400 种，最长 720 字符，**仅 17.1% 有值** |
| `source_type` | VARCHAR(32) | 只有 3 种：`mixed` / `primary` / `secondary` |
| `language` | VARCHAR(32) | 只有 4 种：`英文`/`德文`/`混合`/`波兰文` |
| `stance` | VARCHAR(32) | 只有 4 种（中文值） |
| `period` | VARCHAR(32) | 275 种，最长 9 字符 |
| `region` | ARRAY, max_capacity=**32** | 实测**最多 23 个**元素，30 种取值 |
| `subfield` | ARRAY, max_capacity=**16** | 实测**最多 8 个**元素，8 种取值 |
| `doc_number` | VARCHAR(32), nullable | 10,874 种，最长 5 字符，**仅 13.1% 有值** |
| `doc_date` | VARCHAR(32), nullable | 3,978 种，最长 10 字符，**仅 13.0% 有值** |
| `doc_section` | VARCHAR(64), nullable | 1 种，**仅 201 行有值** |
| `doc_part` / `page_num` / `chunk_index` | INT64 | Chroma 里本来就是 int 类型 |

### 索引参数

```python
def build_index():
    idx = MilvusClient.prepare_index_params()
    idx.add_index(field_name="dense",  index_type="AUTOINDEX", metric_type="L2")
    idx.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
                  params={"inverted_index_algo": "DAAT_MAXSCORE",
                          "bm25_k1": 1.2, "bm25_b": 0.75})
    # 标量索引（可选，但值得建）—— 官方：向量字段强制建索引，标量字段可选
    idx.add_index(field_name="source_type", index_type="BITMAP")   # 基数 3
    idx.add_index(field_name="language",    index_type="BITMAP")   # 基数 4
    idx.add_index(field_name="stance",      index_type="BITMAP")   # 基数 4
    idx.add_index(field_name="title",       index_type="BITMAP")   # 基数 190
    idx.add_index(field_name="region",      index_type="BITMAP")   # 数组，基数 30
    idx.add_index(field_name="subfield",    index_type="BITMAP")   # 数组，基数 8
    idx.add_index(field_name="page_num",    index_type="STL_SORT") # 范围过滤
    idx.add_index(field_name="chunk_index", index_type="STL_SORT") # 范围过滤
    return idx
```

> `metric_type="L2"` 是对的：实测本地向量 **已归一化**（L2 范数 = 1.0000000014），此时 L2 与 COSINE 排序完全一致，换哪个都不会改变结果。
> `BITMAP` 适用基数 < 500（官方原话），你的所有过滤字段都在这个范围内。

---

## 阶段 2：本地导出

**先说结论：不需要中间文件。** 直接从 Chroma 读到内存，分批灌给 Zilliz 即可（见阶段 3）。
只有未来扩到百万级、需要断点续传时，才值得落盘成 Parquet。

```python
# export_plan.py —— 实测吞吐：510 行/秒（含 JSON 序列化）；纯读 3,052 块/秒
import numpy as np
col = get_collection()
BATCH = 1000
off = 0
while True:
    r = col.get(limit=BATCH, offset=off,
                include=["embeddings", "documents", "metadatas"])
    if not r["ids"]:
        break
    embs = r["embeddings"].astype(np.float32)     # ★ 必须转，见下
    for cid, emb, doc, meta in zip(r["ids"], embs, r["documents"], r["metadatas"]):
        yield cid, emb, doc, meta
    off += len(r["ids"])
```

### ★ 三个必须处理的坑

**① `embeddings` 返回的是 float64，不是 float32。**
实测 `dtype=float64 shape=(20000, 1024)`。直接发给 Milvus 会被拒（`FLOAT_VECTOR` 要 float32），或者载荷翻倍（1.25 GB 而不是 627 MB）。
→ **`embs = r["embeddings"].astype(np.float32)`**

**② 缺失的字段在 Chroma 里是"不存在"，不是空串。**
`doc_number` / `doc_date` / `doc_section` / `doc_part` 只存在于 201～20,954 行。这些字段在 Milvus 里必须 `nullable=True`，插入时**给 `None` 而不是 `""`**。

**③ 数组字段要显式转 list。**
`meta.get("region")` 正常是 list；缺失时需要给 `[]`（Milvus 的 ARRAY 不接受 `None`）。

---

## 阶段 3：导入 Zilliz

### 3.1 直接 insert（推荐，简单）

```python
# import_to_zilliz.py
import numpy as np
from pymilvus import MilvusClient
from schema_def import build_schema, COLLECTION

URI, TOKEN = "<uri>", "<token>"
cli = MilvusClient(uri=URI, token=TOKEN)
if cli.has_collection(COLLECTION):
    cli.drop_collection(COLLECTION)
cli.create_collection(COLLECTION, schema=build_schema(), index_params=build_index())

SCALAR_STR = ["title", "chapter_title", "source_type", "language", "stance",
              "period", "doc_number", "doc_date", "doc_section"]
SCALAR_INT = ["chunk_index", "page_num", "doc_part"]
ARRAYS     = ["region", "subfield"]

def to_row(cid, emb, doc, meta):
    row = {"chunk_id": cid, "dense": emb.tolist(), "text": doc}
    for k in SCALAR_STR:
        v = meta.get(k)
        row[k] = v if isinstance(v, str) and v else None
    for k in SCALAR_INT:
        v = meta.get(k)
        row[k] = int(v) if isinstance(v, (int, float)) else None
    for k in ARRAYS:
        v = meta.get(k)
        row[k] = list(v) if isinstance(v, (list, tuple)) else []
    # ★ 不要放 sparse —— 由 BM25 Function 自动生成
    return row

buf, n = [], 0
for cid, emb, doc, meta in export_plan():
    buf.append(to_row(cid, emb, doc, meta))
    if len(buf) >= 500:
        cli.insert(COLLECTION, buf); n += len(buf); buf = []
        print(f"  {n} 行", flush=True)
if buf:
    cli.insert(COLLECTION, buf); n += len(buf)
cli.flush(COLLECTION)

got = cli.query(COLLECTION, filter="", output_fields=["count(*)"])[0]["count(*)"]
print(f"导入 {n} 行，服务端 count = {got}")
assert int(got) == 160475, "行数不匹配！"
```

**用时预期**：Serverless 写入限速 **10 MB/s**，载荷 927 MB → **最少 93 秒**，实际因网络往返约 **5–15 分钟**。

### 3.2 走 Import（写入费 ¥0，未来扩容时用）

官方明文：**Import 和 bulk insert 不产生写入费用**。直接用 `insert()` 的写入费约 **¥5**（见附录 B），所以现在不值得为省这 ¥5 去配 OSS。

但**未来扩到百万级时值得**：Import 支持单次 ≤1TB / 单文件 ≤10GB / ≤1000 个文件，且免写入费。

> ⚠️ **`bulkInsert()` 在 Zilliz 所有档位都不支持**（官方功能矩阵 ✘），必须走 Import 接口。

---

## 阶段 4：适配器 —— `app.py` 零改动的关键

`app.py` 只用到了 collection 的三样能力。我逐行核对过全部调用点：

| 位置 | 调用 | 用到的 where 算子 |
|---|---|---|
| `app.py:352` `tool_expand_chunk` | `get(where=$and[title eq, chunk_index gte, chunk_index lte], include=[documents,metadatas])` | `$eq` `$gte` `$lte` `$and` |
| `app.py:408` `tool_get_book_info` | `get(where=title eq, include=[])` → `len(ids)` | `$eq` |
| `app.py:433` `tool_list_sources_on_topic` | `query(query_embeddings, n_results, include=[metadatas,distances])` | 向量检索 |
| `app.py:478` `tool_list_books_by_filter` | `get(where=..., include=[metadatas], limit=5000)` | `$contains`（数组） |
| `app.py:1896` 侧栏 | `col.count()` | — |
| `corpus_lib.get_book_counts` | `get(include=[])["ids"]` | 全表扫 |
| `corpus_lib.get_chunks_for_book` | `get(where=title eq, include=[documents,metadatas])` | `$eq` |
| `corpus_lib.get_chapters_for_book` | `get(where=title eq, include=[metadatas])` | `$eq` |
| `corpus_lib.get_chunks_by_ids` | `get(ids=[...], include=[documents,metadatas])` | 主键 |
| `corpus_lib.search_chunks` | `query(query_embeddings, where, n_results, include)` | 向量检索 + 全部算子 |

**只需覆盖 `count` / `get` / `query` 三个方法 + 一个 where 翻译器。**

```python
# milvus_backend.py —— 让 Milvus 冒充 chromadb.Collection
from pymilvus import MilvusClient

COLLECTION = "habsburg"

META_FIELDS = ["title", "chunk_index", "page_num", "chapter_title", "source_type",
               "language", "stance", "period", "region", "subfield",
               "doc_number", "doc_date", "doc_section", "doc_part"]
_NEVER_OUTPUT = {"sparse"}          # ★ sparse 不能出现在 output_fields 里，会报错


def _q(v):
    """把 Python 值转成 Milvus 表达式字面量"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + s + "'"


_OPS = {"$eq": "==", "$ne": "!=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}


def where_to_expr(where):
    """Chroma where 字典 → Milvus 过滤表达式。已核对语料里没有引号/反斜杠注入隐患。"""
    if not where:
        return ""
    parts = []
    for k, v in where.items():
        if k in ("$and", "$or"):
            joiner = " and " if k == "$and" else " or "
            subs = [where_to_expr(x) for x in v]
            parts.append("(" + joiner.join(s for s in subs if s) + ")")
        elif isinstance(v, dict):
            for op, val in v.items():
                if op == "$contains":                       # region / subfield 数组
                    parts.append("ARRAY_CONTAINS(%s, %s)" % (k, _q(val)))
                elif op == "$in":
                    parts.append("%s in [%s]" % (k, ", ".join(_q(x) for x in val)))
                elif op == "$nin":
                    parts.append("%s not in [%s]" % (k, ", ".join(_q(x) for x in val)))
                elif op in _OPS:
                    parts.append("%s %s %s" % (k, _OPS[op], _q(val)))
                else:
                    raise ValueError("不支持的算子: " + op)
        else:
            parts.append("%s == %s" % (k, _q(v)))
    return " and ".join(parts)


def _row_to_meta(r):
    """Milvus 行 → Chroma 风格的 meta 字典（缺的字段给 None/空，与原来一致）"""
    return {
        "title":         r.get("title"),
        "chunk_index":   r.get("chunk_index"),
        "page_num":      r.get("page_num"),
        "chapter_title": r.get("chapter_title") or "",
        "source_type":   r.get("source_type"),
        "language":      r.get("language"),
        "stance":        r.get("stance"),
        "period":        r.get("period"),
        "region":        r.get("region") or [],
        "subfield":      r.get("subfield") or [],
        "doc_number":    r.get("doc_number"),
        "doc_date":      r.get("doc_date"),
        "doc_section":   r.get("doc_section"),
        "doc_part":      r.get("doc_part"),
    }


class MilvusCollection:
    """实现 chromadb Collection 的 count / get / query 三个方法"""

    def __init__(self, uri, token, name=COLLECTION):
        self._cli = MilvusClient(uri=uri, token=token)
        self._name = name

    # ---------- count ----------
    def count(self):
        r = self._cli.query(self._name, filter="", output_fields=["count(*)"])
        return int(r[0]["count(*)"])

    # ---------- get ----------
    def get(self, ids=None, where=None, include=None, limit=None, offset=0):
        include = include or []
        fields = ["chunk_id"]
        if "metadatas" in include:
            fields += META_FIELDS
        if "documents" in include:
            fields.append("text")
        if "embeddings" in include:
            fields.append("dense")
        fields = [f for f in fields if f not in _NEVER_OUTPUT]

        if ids:
            filt = "chunk_id in [%s]" % ", ".join(_q(i) for i in ids)
        else:
            filt = where_to_expr(where)

        # 无 limit 时用 iterator 做全表扫（get_book_counts 要 16 万行）
        if limit is None and not ids:
            it, rows = self._cli.query_iterator(
                self._name, filter=filt or "", output_fields=fields, batch_size=5000), []
            while True:
                b = it.next()
                if not b:
                    it.close()
                    break
                rows += b
        else:
            rows, off, want = [], offset, limit or 10 ** 9
            while len(rows) < want:
                n = min(2000, want - len(rows))
                b = self._cli.query(self._name, filter=filt or "", output_fields=fields,
                                    limit=n, offset=off)
                if not b:
                    break
                rows += b
                off += len(b)
                if len(b) < n:
                    break

        out = {"ids": [r["chunk_id"] for r in rows]}
        if "documents" in include:
            out["documents"] = [r.get("text", "") for r in rows]
        if "metadatas" in include:
            out["metadatas"] = [_row_to_meta(r) for r in rows]
        if "embeddings" in include:
            out["embeddings"] = [r.get("dense") for r in rows]
        return out

    # ---------- query（向量检索）----------
    def query(self, query_embeddings=None, where=None, n_results=10, include=None):
        include = include or []
        fields = ["chunk_id"] + META_FIELDS
        if "documents" in include:
            fields.append("text")
        hits = self._cli.search(
            self._name,
            data=[list(map(float, query_embeddings[0]))],
            anns_field="dense",
            search_params={"metric_type": "L2"},
            limit=min(n_results, 1024),                 # ★ Serverless topK 上限 1024
            filter=where_to_expr(where) or "",
            output_fields=fields,
        )[0]
        out = {"ids": [[h["chunk_id"] for h in hits]]}   # ★ 不是 h["id"]，见下
        if "documents" in include:
            out["documents"] = [[h["entity"].get("text", "") for h in hits]]
        if "metadatas" in include:
            out["metadatas"] = [[_row_to_meta(h["entity"]) for h in hits]]
        if "distances" in include:
            out["distances"] = [[h["distance"] for h in hits]]
        return out

    # ---------- 全文腿（Chroma 没有的能力，供 search_chunks 用）----------
    def search_sparse(self, query_text, where=None, limit=100):
        fields = ["chunk_id"] + META_FIELDS + ["text"]
        fields = [f for f in fields if f not in _NEVER_OUTPUT]
        return self._cli.search(
            self._name, data=[query_text],              # ★ BM25 传原始文本，不传向量
            anns_field="sparse",
            search_params={"metric_type": "BM25"},
            limit=min(limit, 1024),
            filter=where_to_expr(where) or "",
            output_fields=fields,
        )[0]
```

### 接线：`corpus_lib.get_collection()` 改成可切换

```python
# corpus_lib.py
import config

_collection = None

def get_collection():
    global _collection
    if _collection is None:
        with _collection_lock:
            if _collection is None:
                if config.BACKEND == "zilliz":
                    from milvus_backend import MilvusCollection
                    _collection = MilvusCollection(config.ZILLIZ_URI, config.ZILLIZ_TOKEN)
                else:                                   # 原路径，保留作回滚
                    import chromadb
                    _collection = chromadb.PersistentClient(
                        path=CHROMA_DB_PATH).get_or_create_collection(COLLECTION_NAME)
    return _collection
```

```python
# config.py 追加
BACKEND       = os.environ.get("HABRAG_BACKEND", "chroma")   # chroma | zilliz
ZILLIZ_URI    = os.environ.get("ZILLIZ_URI", "")
ZILLIZ_TOKEN  = os.environ.get("ZILLIZ_TOKEN", "")
```

**做完阶段 4，`app.py` 一行都不用改，整个应用就能跑在新后端上。** 这是回滚成本最低的切法。

---

## 阶段 5：改造 `search_chunks` 的检索层

只有这一个函数需要动。**方案 B（客户端融合）优先**，因为它复用你现有的 `_rrf_merge`，行为完全透明，也方便和本地后端 A/B 对比。

### 方案 B：客户端两腿融合（推荐先做）

```python
# corpus_lib.search_chunks 内，替换每条查询的两腿部分
for q in queries:
    vec, ft = [], []
    if config.BACKEND == "zilliz":
        # ---- 稠密腿 ----
        try:
            q_emb = embed_text(q)
            hits = collection._cli.search(
                "habsburg", data=[q_emb], anns_field="dense",
                search_params={"metric_type": "L2"},
                limit=min(n_results * 3, 1024),
                filter=mb.where_to_expr(where) or "",
                output_fields=["chunk_id", "text"] + mb.META_FIELDS,
            )[0]
            vec = [(mb._row_to_meta(h["entity"]), h["entity"].get("text", ""),
                    h["distance"]) for h in hits]
        except Exception as e:
            _dbg("检索增强 · 向量检索失败", {"query": q, "error": str(e)})
        # ---- 全文腿：BM25 稀疏 ----
        try:
            sh = mb.MilvusCollection.search_sparse(collection, q, where=where,
                                                   limit=min(n_results * 3, 1024))
            ft = [(mb._row_to_meta(h["entity"]), h["entity"].get("text", ""),
                   h["distance"]) for h in sh]
        except Exception as e:
            _dbg("检索增强 · 全文检索失败", {"query": q, "error": str(e)})
        for meta, _doc, dist in vec:
            cid = _chunk_id_of(meta)
            if cid not in dist_map or dist < dist_map[cid]:
                dist_map[cid] = dist
    else:
        ... 原来的 Chroma 两腿，原样保留 ...
```

**`_rrf_merge` 与跨查询融合完全不动**——Milvus 的 `RRFRanker` 默认 `k=60`，和你 `_RRF_K = 60` 本来就一致。

### 方案 A：服务端 `hybrid_search`（后续优化）

把每条查询的两腿合并成一次调用，减少往返：

```python
from pymilvus import AnnSearchRequest, RRFRanker
reqs = [
    AnnSearchRequest(data=[q_emb], anns_field="dense",
                     param={"metric_type": "L2"}, limit=cand, expr=expr),
    AnnSearchRequest(data=[q], anns_field="sparse",
                     param={"metric_type": "BM25"}, limit=cand, expr=expr),
]
hits = collection._cli.hybrid_search(
    "habsburg", reqs, ranker=RRFRanker(60), limit=cand,
    output_fields=["chunk_id", "text"] + META_FIELDS)
```

> ⚠️ 两个源码级陷阱：`AnnSearchRequest` 的 `param` 是**必填位置参数**（官方文档示例漏传会 `TypeError`）；
> `hybrid_search` **没有顶层 `filter` 参数**，过滤条件必须写进**每个** `AnnSearchRequest(expr=...)`。

### 要删掉的东西

| 函数 | 处置 |
|---|---|
| `fulltext_query()` | **删除**（被 BM25 稀疏腿取代）。它连带的 FTS5 语法清洗、`ORDER BY rank`、`_FULLTEXT_ERR` 全部作废 |
| `_FTS_URI` | 删除 |
| `_meta_matches()` | 删除（Chroma 侧的 Python 过滤，Milvus 用 `filter` 表达式） |
| `_FULLTEXT_OK` / `_FULLTEXT_ERR` | 改为在 Milvus 路径下恒为 `True`（保留开发者模式的日志位） |

**好消息**：`ORDER BY rank` 那个随库线性恶化的性能问题**自动消失**——Milvus 的 `SPARSE_INVERTED_INDEX` 用 `DAAT_MAXSCORE` 剪枝，排序检索的延迟不随匹配行数线性增长。

---

## 阶段 6：验收

### 6.1 必过的回归：12 术语基准

用 `docs/OPERATIONS.md` 第 3.3 节那套基准，对比迁移前后：

```
迁移前（本地 trigram FTS5）：全文腿 recall@30 = 100.0%   向量腿 recall@30 = 47.4%

Zwischenzollinie 25    Probemobilisierung 28    Szogyeny 292      Bogicevic 257
Czernin 1353           Hötzendorf 401           Annexionskrise 140 Teilungsvertrag 6
Zwischenfall 162       Kriegsministerium 1068   Ausgleich 1621    Ultimatum 1989
```

**判定线：BM25 稀疏腿的 recall@30 不得低于 95%。** 低于此说明词元语义替代不了子串语义，需要补一条 `TEXT_MATCH` 兜底腿（官方支持，需 `enable_analyzer+enable_match`）。

### 6.2 端到端对比

同一条问题，分别在 `HABRAG_BACKEND=chroma` 和 `=zilliz` 下跑，比较：
- 单次 `search_chunks` 耗时（关闭 rerank，纯两腿+RRF）
- top-10 的重合度（若重合度低，看差异是"更差"还是"另一种合理排序"）
- `enrich_chunk` 输出是否完整（引注格式 `ÖUA VIII, Nr. 10364` 必须照常生成）

### 6.3 逐一验证五个工具

`tool_expand_chunk` / `tool_get_book_info` / `tool_list_sources_on_topic` / `tool_list_books_by_filter` / 侧栏状态——这五个是 `app.py` 直接调 collection 的地方，**走得通就说明适配器翻译正确**。

---

## 阶段 7：切换与回滚

### 7.1 已完成的代码改动（2026-10-01）

| 文件 | 改动 |
|---|---|
| `config.py` | 新增 `import os`；新增 `BACKEND` / `ZILLIZ_URI` / `ZILLIZ_TOKEN` / `ZILLIZ_COLLECTION` 四项（均可用环境变量覆盖）。默认 `BACKEND="chroma"` |
| `milvus_backend.py` | **新增**。`MilvusCollection` 类实现 `count/get/query` 三个方法，把 Milvus 包装成 chromadb.Collection；另加 `search_dense` / `search_sparse` 供检索层使用。含 `where_to_expr()`（Chroma where → Milvus 表达式）与 `row_to_meta()` |
| `corpus_lib.py` | ① 顶部 import 增加 `BACKEND` / `ZILLIZ_*`；② 新增 `using_milvus()`；③ `get_collection()` 按 `BACKEND` 分派；④ `search_chunks()` 的两条腿按后端分派——本地走 `fulltext_query`(FTS5)，云端走 `search_sparse`(BM25)。**`_rrf_merge` 与跨查询融合完全未动** |
| `app.py` | ★ **修掉一个会让切换失效的坑**：原 `app.py:143-146` 自建 `chromadb.PersistentClient`，绕过 `BACKEND` 开关。已删除该定义，改为从 `corpus_lib` 导入 `get_collection`（5 处调用点全部生效） |
| `migrate_to_zilliz.py` | **新增**。生产导入脚本（`--drop` 重建 / 不带则续传） |
| `validate_zilliz.py` | **新增**。生产集合验证脚本（召回基准 + 全部调用点 + 五个工具） |
| `smoke_test.py` / `recall_test.py` | 冒烟与召回验证脚本，可重跑 |

**`fulltext_query`、`_FTS_URI`、`_meta_matches` 全部保留未删** —— Chroma 路径完整可用，这是回滚的安全垫。

### 7.2 切换

```powershell
$env:HABRAG_BACKEND = "zilliz"
$env:ZILLIZ_URI     = "https://<cluster-id>.serverless.ali-cn-hangzhou.cloud.zilliz.com.cn"
$env:ZILLIZ_TOKEN   = "<API Key>"
streamlit run app.py
```

> 注意：中国区 Serverless 的域名后缀是 **`.cloud.zilliz.com.cn`**（不是国际站的
> `.vectordb.zillizcloud.com`），且**不带端口**。

**切换前先跑验证**：

```powershell
python validate_zilliz.py
```

它会检查：后端是否真的切过去、服务端行数是否 160,475、12 术语 + 3 档案号的 recall@30、
端到端检索耗时、`corpus_lib` 全部调用点、`app.py` 五个工具函数。

### 7.3 回滚

```powershell
Remove-Item Env:\HABRAG_BACKEND      # 或显式设为 "chroma"
streamlit run app.py
```

本地 `db/` 一个字节未动，Chroma 路径代码未删，回滚是即时的。

**在 `validate_zilliz.py` 全部通过之前，不要删本地 `db/`。**

### 7.4 数据侧现状（2026-10-01）

| 项 | 值 |
|---|---|
| 目标集合 | `habsburg`（Zilliz Cloud Serverless，ali-cn-hangzhou） |
| 灌入行数 | **160,475**（与源库精确一致） |
| 灌入耗时 | **415 秒**（386 条/秒） |
| 向量 | 直接复制，**未重新调用 embedding API** |
| 临时测试集合 | 已全部 drop，`list_collections()` 现为 `["habsburg"]` |

### 7.5 ★ 生产集合验证结果（`validate_zilliz.py`，全部通过，退出码 0）

**召回（真值来自全库 160,475 条，非抽样；两侧折叠变音符后子串匹配）**

| 查询词 | 真值数 | Milvus BM25 | 稠密腿 |
|---|---:|---:|---:|
| Zwischenzollinie | 25 | **100%** | 0% |
| Probemobilisierung | 28 | **100%** | 0% |
| Szogyeny | 1271 | **100%** | 0% |
| Bogicevic | 257 | **100%** | 90% |
| Czernin | 1353 | **100%** | 100% |
| Hötzendorf | 633 | **100%** | 43% |
| Annexionskrise | 140 | **100%** | 33% |
| Teilungsvertrag | 12 | **100%** | 17% |
| Zwischenfall | 259 | **100%** | 3% |
| Kriegsministerium | 1068 | **100%** | 60% |
| Ausgleich | 1621 | **100%** | 83% |
| Ultimatum | 2017 | **100%** | 100% |
| **平均** | | **100.0%** | 44.2% |
| 档案号 10364 / 0050 / 0005 | 9 / 42 / 78 | **100% / 100% / 100%** | — |

这张表也**量化了为什么全文腿不能砍**：稠密腿在这 12 个领域术语上平均只有 44.2%，
其中 `Zwischenzollinie`、`Probemobilisierung`、`Szogyeny` 是 **0%**。
BM25 与稠密腿互补，不是冗余。

**端到端与调用点**

```
[D] search_chunks（生产集合，关闭 rerank/rewrite）
    Zwischenzollinie         5 条   1014 ms
    ÖUA VIII, Nr. 10364      5 条    927 ms   ← 目标档案精确出现在第 2 位
    Conrad von Hötzendorf    5 条   1037 ms
    带 source_type=primary 过滤  5 条  953 ms   过滤全部生效

[E] get_chunks_by_ids      -> 命中
    get_chunks_for_book    -> 2576 块   (23.4s)   ← 偏慢，见下
    get_chapters_for_book  -> 0 个章节
    get_book_counts        -> 190 书目 / 160475 块  (6.7s)

[F] tool_expand_chunk / tool_get_book_info / tool_list_sources_on_topic
    / tool_list_books_by_filter  -> 全部正常
```

**延迟对比（重要）**

| 后端 | 三条查询平均 |
|---|---:|
| 本地 Chroma | **935 ms** |
| Zilliz Cloud | **993 ms** |

**差 58 ms。** 这 ~950 ms 的大头是 `embed_text()`（SiliconFlow API），两个后端都要付。
**迁移在延迟上几乎零代价**——网络往返不是瓶颈。

**唯一需注意的慢点**：`get_chunks_for_book` 取单本书全部 chunk（2,576 块）耗时 **23.4 秒**
（本地 Chroma 是毫秒级）。它在 `pages/1_语料浏览.py` 里被 `@st.cache_data(ttl=600)` 包着，
所以每个书目首次打开会等 20 多秒，10 分钟内不会重复。
若要根治，可改用 `query_iterator` 流式分页，或把书名→块数改成入库时落盘的缓存。

### 7.6 写入路径验证（`test_adapter_write.py`，12/12 通过）

读取路径验证过之后，**写入路径最初是缺的**——`MilvusCollection` 只有 `count/get/query`，
而项目里这些地方会写库：

```
ingest.py              : collection.add(...) / collection.delete(ids=[...])
ingest_new.py          : collection.delete(where={"title":...}) 然后 add(...)
clean.py               : collection.delete(where={"title":...})
pages/2_文献库管理.py   : 同上（「重新入库」= 先删后加，chunk_id 会重叠）
```

已补上 `add()` / `upsert()` / `delete(ids=|where=)`，并在真实集群上用独立临时集合验证 12 项：

| # | 验证项 | 结果 |
|---|---|---|
| 1 | `add`（3 条，含空数组与缺字段） | PASS |
| 2 | `count` | PASS |
| 3 | `get(ids=[...])` | PASS |
| 4 | `get(where={"title": ...})` | PASS |
| 5 | `get($and + $gte/$lte)`（app.py 的 expand_chunk 路径） | PASS |
| 6 | `get(数组 $contains)`（region/subfield 过滤） | PASS |
| 7 | `query`（向量检索） | PASS |
| 8 | ★ **重新入库：`delete(where)` + `add` 相同 chunk_id** | PASS |
| 9 | `delete(ids=[...])`（ingest.py 的失败回滚） | PASS |
| 10 | `upsert` | PASS |
| 11 | `get(limit=)`（app.py 的 limit=5000 路径） | PASS |
| 12 | `get(include=[])` 全表扫（get_book_counts 路径） | PASS |

**第 8 项是最关键的**——「重新入库」会先删掉整本书再重新切块写回，
新 chunk_id 与旧的重叠，这正是 Milvus 最容易出 tombstone 问题的模式。实测正常。

### 7.7 删掉本地 `db/` 会怎样

**结论：Streamlit 应用可以正常运行，但迁移/校验类脚本会失效。建议暂不删除。**

| 功能 | 无本地 `db/` 时（BACKEND=zilliz） |
|---|---|
| 检索 `search_chunks`（含向量腿 + BM25 腿 + 元数据过滤） | ✅ |
| 语料浏览 `pages/1_语料浏览.py` | ✅ |
| 文献库管理 `pages/2_文献库管理.py`（重新入库 / 删除该书） | ✅ |
| `app.py` 五个工具函数 | ✅ |
| `db_check.py` | ✅（走 `corpus_lib.get_book_counts()`） |
| `ingest.py` / `ingest_new.py` / `clean.py` | ✅（已改为走 `corpus_lib.get_collection()`） |
| `validate_zilliz.py` / `recall_test.py` | ❌ 读本地 `chroma.sqlite3` 算真值 |
| `restore_from_zilliz.py` | ❌ 写回本地 Chroma |
| `migrate_to_zilliz.py` | ❌ 从本地导出 |

**建议：先不要删。** 三条理由：
1. 它是唯一的回滚路径 —— 云端出任何问题，`db/` 就是退路
2. 只有 3 GB，保留成本可忽略
3. 今天才刚验证完，跑几天真实使用再决定更稳妥

真要删，先挪到别的盘留档（例如 `D:\habRAG_db_backup`），别直接 `Remove-Item`。

### 7.8 成本实测复盘：写入 ¥9 是怎么来的

官方计费口径（中国区列表价）：

| 项 | 单价 |
|---|---|
| 读/写 vCU | **¥21 / 百万 vCU** |
| **Insert** | **1 KB = 0.25 vCU** |
| **Delete** | **1 个实体 = 1 vCU**（**删不存在的也收 1 vCU**） |
| **Import（走 OSS）** | **¥0** —— 官方明文"Import 和 bulk insert 不产生写入费用" |
| 存储 | ¥1.2 / GB / 月 |
| 读取 | 最低 6 vCU/次 |

单行逻辑大小实测 ≈ **6,058 B**（向量 4,096 + 正文 1,764 + 标量 ~200）。

**2026-10-01 这一天实际发生的写入：**

| 操作 | 行数 | 费用 |
|---|---:|---:|
| **生产迁移**（`migrate_to_zilliz.py`） | 160,475 | **≈ ¥5.1** |
| 召回验证 3 轮上传（`recall_test.py`） | 98,555 | ≈ ¥3.1 |
| 召回验证 3 次 `drop_collection`（= 删 98,555 实体） | 98,555 | ≈ ¥2.1 |
| 冒烟/适配器测试 | ~20 | ≈ ¥0 |
| **合计** | | **≈ ¥10.3** |

**所以 ¥9 里大约一半是生产迁移，一半是做验证烧掉的。**
生产迁移本身 = **¥5.1 一次性**。

#### ★ 下次大批量注入应该走 Import，写入费为 ¥0

| 规模 | 走 `insert` | 走 `Import` |
|---|---:|---:|
| 当前 16 万行 | ¥5.1 | **¥0** |
| 扩到 160 万行（`db/` 约 30 GiB） | **≈ ¥51** | **¥0** |

Import 还更快（Serverless 的 `insert` 限速 10 MB/s，实测 386 条/秒 ≈ 2.3 MB/s）。
代价是要先把文件传到 OSS，并遵守 Import 的限制（单次 ≤1TB、单文件 ≤10GB、≤1000 文件）。

> ⚠️ `bulkInsert()` 在 Zilliz **所有档位都不支持**，只能用 Import 接口。

#### 成本结构认知

| 项 | 量级 |
|---|---|
| 写入 | **一次性 ¥5.1 / 16 万行**（走 Import 则 ¥0）—— 是这里最大的一笔 |
| 存储 | ¥1.3 / 月（1.08 GB） |
| 读取 | ≈ ¥0.001 / 次提问（每次约 8–10 次读取） |
| 单本重灌（删 1,541 + 写 1,541） | ≈ ¥0.08 |

**结论：写入是一次性且可归零的；存储和读取几乎可忽略。**
`drop_collection` 也要小心——销毁一个 16 万的集合 = ¥3.37（按实体计费），
这也是为什么 7.5 节那个 48 秒的 `drop_collection` 不只是慢，还在计费。

---

## 附录 A：Milvus 2.6 的 8 个坑（源码级证据）

| # | 坑 | 证据 / 后果 |
|---|---|---|
| 1 | **`AnnSearchRequest(data, anns_field, param, limit, expr=None)` 的 `param` 是必填位置参数** | 官方文档示例里那段省掉 `param` 的 BM25 请求，在 pymilvus 2.6 上直接 `TypeError` |
| 2 | **`hybrid_search` 没有顶层 `filter`** | 2.6 签名只有 `(collection_name, reqs, ranker, limit=10, output_fields=None, timeout=None, partition_names=None, **kwargs)`，`**kwargs` 只文档化了 `offset`/`consistency_level`。过滤必须写进每个 `AnnSearchRequest(expr=...)` |
| 3 | **`sparse` 字段不能出现在 `output_fields` 里** | 会报错。适配器里用 `_NEVER_OUTPUT` 统一挡掉 |
| 4 | **插入时不要给 `sparse` 赋值** | 官方原文 "you need only to provide the raw text"。BM25 Function 自动算 |
| 5 | **BM25 那一路 `data` 传原始查询文本** | 不是预计算的稀疏向量 |
| 6 | **API 参考页写 hybrid_search "applies only to dedicated serving clusters"** | 判为**文档模板残留**：同一句逐字出现在 `search()` 参考页，而 `search()` 在官方功能矩阵里是 Serverless ✔︎。但这是唯一可能被引用来反驳的点，冒烟测试里已列为第 7 项 |
| 7 | **`client.search` 用 `search_params=`，`AnnSearchRequest` 用 `param=`** | 两者参数名不同，容易混 |
| 8 | **内置 analyzer 只有 `standard` / `english` / `chinese`** | `jieba` 是 **tokenizer** 不是 analyzer。`strip_accents` 在 Milvus 里**根本不存在**（那是 ES/Bleve 的概念），等价物是无参的 `asciifolding` |
| 9 | **search 命中对象是 dict-like，主键字段在顶层，没有 `h["id"]`** | 实测 2.6.17：`dict(hit) == {'chunk_id': 'a::0', 'distance': 0.0, 'entity': {...}}`。取主键要用 `hit["chunk_id"]`（前提是它出现在 `output_fields` 里），取字段用 `hit["entity"][...]`，距离用 `hit["distance"]`。**用 `h["id"]` 会 `KeyError`** |
| 10 | **`run_analyzer` 的签名是 `texts=`（复数）** | `run_analyzer(texts=[...], analyzer_params={...})`，返回 `list[AnalyzeResult]`，分词结果在 `.tokens`。传 `text=` 会 `TypeError` |
| 11 | **pymilvus 2.6.17 上没有 `add_function_field`** | 实际方法名是 `add_collection_function`（`add_function_field` 是 Milvus 3.0 的名字）。但即使名字对了，Serverless 也会拒绝：`code=1100 currently does not support adding BM25 function` |

### 关于变音符（重要）

官方 `ascii-folding-filter.md` 的期望输出是决定性证据：

```
Input:  "Café Möller serves crème brûlée and piñatas."
Output: ['Cafe', 'Moller', 'serves', 'creme', 'brulee', 'and', 'pinatas']
```

`Möller → Moller`（**ö→o**），不是 `Moeller`。tantivy 折叠表逐字印证 `'ö' => Some("o")`。1→2 展开只发生在连字和 ß 上（`œ→oe`、`æ→ae`、`ß→ss`）。

**对你的语料意味着：**

| 查询 | 现在（FTS5 trigram） | 迁移后（asciifolding） |
|---|---|---|
| `Bogicevic` ↔ `Bogićević` | ❌ 前者 257 条、后者 **0 条** | ✅ **两者都能匹配** —— 这是净改善 |
| `Hötzendorf` ↔ `Hoetzendorf` | ❌ 401 条 vs **16 条** | ❌ `hotzendorf` vs `hoetzendorf`，**仍不匹配** |
| `Hotzendorf` ↔ `Hötzendorf` | ❌ | ✅ 现在能匹配 |

**德语元音展开（ö↔oe）Milvus 2.6 没有任何 filter 能做。** 如果这是硬需求，唯一方案是**双文本字段 + 双 BM25 Function**（一个存原文，一个存归一化副本）——但注意 Serverless 每集合向量字段上限 **4 个**，双 BM25 会占掉 2 个，够用但要规划。

> 另有一个未验证的可能：`stemmer language="german"` 的 Snowball 预处理理论上有 `oe→ö` 规则，但 Snowball 3.0 才把 german2 的 ASCII 转写并入标准算法，无法核实 Milvus 2.6 链接的 rust-stemmers 版本。**用 `run_analyzer()` 实测即可确认**（analyzer 一建就改不了，值得测）。

---

## 附录 B：成本明细

### 单价（中国区，列表价）

| 项 | 价格 |
|---|---|
| 读/写 vCU | **¥21 / 百万 vCU** |
| Insert | **1 KB = 0.25 vCU** |
| Delete | **1 个 entity = 1 vCU**（删不存在的也收 1） |
| **Import / bulk insert** | **¥0**（官方明文不计写入费） |
| 读取 | **最低 6 vCU/次**，另加扫描量（每次扫描整个 Collection）+ 返回量 |
| 存储 | **¥1.2 / GB / 月**（按小时计费） |
| 公网出口 | ¥0.8/GB，**前 100 GB 免费** |

### 当前规模（160,475 行）

| 项 | 计算 | 金额 |
|---|---|---|
| 存储 | 向量 627 MB + 正文 270 MB + 标量 ~30 MB + 稀疏索引 ~150 MB ≈ 1.08 GB | **≈ ¥1.3 / 月** |
| 写入（`insert`） | 160,475 行 × ~6 KB × 0.25 vCU/KB ≈ 24 万 vCU | **≈ ¥5**（一次性） |
| 写入（Import） | — | **¥0** |
| 读取 | 每次提问约 8–10 次读取（4 查询 × 2 腿 + 按 id 取回） | **≈ ¥0.001 / 次提问** |
| **合计** | | **≈ ¥1.3 / 月 + ¥5 一次性** |

**注册赠 ¥300 券 ≈ 覆盖 19 年存储。**

### 扩到 160 万行（对应 `db/` 约 30 GiB）时

| 项 | 金额 |
|---|---|
| 存储 ≈ 10.3 GB | **≈ ¥12.4 / 月** |
| 读取（每次扫描量 ×10） | ≈ ¥6.6 / 月（按每月 1,000 次提问） |
| 写入（Import） | **¥0** |
| **合计** | **≈ ¥20 / 月** |

### 降低读取费的办法

官方明确：**每次读取会扫描整个 Collection**。可用 **Partition Key** 缩小扫描范围。但你的检索是全库语义检索，分区的收益有限——只有在按 `source_type` 或 `title` 做分区检索时才有意义。当前规模下不值得做。

---

## 附录 C：Serverless 的能力边界（会和不会影响你的）

### ✘ 不支持（但对本项目无影响）

| 能力 | 影响 |
|---|---|
| `CreateDatabase` / `DropDatabase` | 只能用一个默认库。本项目不需要多库，**无影响** |
| `bulkInsert()` | 所有档位都不支持，必须走 Import 接口。已按此规划 |
| nullable StructArray | 不使用嵌套结构，**无影响** |
| 集群级 RBAC 全部 API | 单人项目，**无影响** |
| 集群挂起/恢复 | **Serverless 不支持挂起**——但它本来就是纯按需计费，空闲时计算费天然为 0，**无影响** |
| 自定义词典与分词器 | Milvus 3.0 / 仅按需计算功能，Serverless 不可用。**你可能需要**：如果要用双 BM25 Function 做德语归一化，那是"第二个字段 + 第二个 Function"，不是自定义词典，**可行** |

### ✔ 支持但要留意的硬约束

| 约束 | 数值 | 对本项目 |
|---|---|---|
| 单次查询 topK | **≤ 1,024** | 代码里 `n_results*3` 上限 100，**安全**。适配器仍加了 `min(..., 1024)` 兜底 |
| `nq`（每次查询的向量数） | **≤ 10** | 每条查询只发 1 个向量，**安全** |
| 写入速率 | **10 MB/s** | 927 MB 载荷 → 最少 93 秒，**够用** |
| Shard 数 | **2** | 只影响写入并行度 |
| 每集群 Collection 数 | 100 | 只用 1 个 |
| 向量维度上限 | 32,768 | 用 1,024 |
| 每集合向量字段数 | **4** | 用 2 个（dense + sparse），若做双 BM25 则 4 个，**刚好卡满** |
| 每集合字段总数 | 64 | 用 17 个 |
| Query 响应实体数 | ≤ 16,384 | `get_chunks_for_book` 最大单本 1,748 块，**安全** |
| **容量上限** | **无**（官方原文 "Serverless clusters in Zilliz Cloud have no capacity limits"） | 「100 万」是 **Free 集群**的额度，不是 Serverless |

---

## 附录 D：残留缺口（迁移解决不了的）

| # | 缺口 | 说明 |
|---|---|---|
| 1 | **德语元音展开 ö↔oe** | Milvus 没有 `german_normalization`。需双 BM25 Function 或接受 |
| 2 | **`ORDER BY rank` 的性能问题** | ✅ **迁移后自动消失**（WAND/DAAT_MAXSCORE 剪枝），不用再管 |
| 3 | **FTS5 语法字符问题** | ✅ **自动消失**（Milvus 用 analyzer 分词，不存在保留字） |
| 4 | **`exclude_chunks` 的表达式长度** | 迁移后走 `chunk_id not in [...]`。长会话积累上百个排除项时，表达式会变长——建议分批或改用 `not in` 的独立过滤 |
| 5 | **`relevance = 1 - dist` 的可比性** | Milvus 的 L2 返回平方 L2，与 Chroma 同量纲；但因实现差异，显示的 relevance 数值可能与本地略有出入。仅影响展示，不影响排序 |
| 6 | **`get_book_counts()` 全表扫** | 适配器用 `query_iterator` 拉 16 万个 title。首次约 30 秒，**建议加进程内缓存**（只在重新注入后失效） |

---

## 附录 E：执行清单

```
□ 0.1  注册 cloud.zilliz.com.cn（企业邮箱，1 手机号限 1 账号）
□ 0.2  创建 Serverless 集群（地域只能选杭州）；★保存集群凭证（只展示一次）
□ 0.3  pip install pymilvus；跑 smoke_test.py 的 14 项检查
□ 0.4  全部通过才继续；任一失败 → 停下重新评估
□ 1    写 schema_def.py（字段表已按实测数据给出）
□ 2    写导出迭代器（★ embeddings.astype(np.float32)）
□ 3    import_to_zilliz.py，校验服务端 count == 160475
□ 4    写 milvus_backend.py + 改 corpus_lib.get_collection() + config.py 加开关
□ 4'   ★此时 app.py 应能零改动跑起来，先验证五个工具
□ 5    改 search_chunks 两条腿（方案 B），删 fulltext_query / _meta_matches / _FTS_URI
□ 6.1  12 术语 recall@30 ≥ 95%
□ 6.2  端到端耗时与 top-10 对比
□ 6.3  五个工具 + 引注格式逐一验证
□ 7    HABRAG_BACKEND=zilliz 切生产；★保留本地 db/ 与 chroma 代码路径
```
