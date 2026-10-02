# 阿里云 Zilliz Cloud（中国区）Serverless 集群调研报告

调研目标：把 160 万行 / 1024 维向量的 Milvus 集合迁到 Zilliz Cloud 中国区 Serverless，确认能力是否足够。
调研日期：2026-09-24
核实原则：只报告能从官方文档/官方定价页核实的事实，每条附 URL。无法核实的明确标「未找到」。

**取证方法说明（重要）**：`docs.zilliz.com.cn` 的页面因左侧导航过长，普通抓取会被截断（只剩导航栏）。两种可行取证路径：
- `docs.zilliz.com`（国际站）支持在任意文档 URL 后加 `.md` 直接取原始 Markdown，内容最完整：如 `https://docs.zilliz.com/docs/limits.md`
- 中国站页面若属于「运维指南」章节（导航较短）可完整抓取；属于「开发指南」章节的会被截断
- 中国站与国际站的文档内容基本一致，本报告对关键结论尽量同时给出中国站 URL

---

## 1. 创建流程

**注册账号（cloud.zilliz.com.cn）**

- 注册入口：https://cloud.zilliz.com.cn/signup （页面本身在 zilliz.com.cn 顶部「免费试用」按钮指向同一地址）
- 注册字段与顺序（官方逐条步骤）：① 企业邮箱 → ② 点「获取验证码」并填入邮件验证码 → ③ 设置密码（8–128 字符，须含大写、小写、数字、至少一个特殊字符）→ ④ 填写手机号（**每个手机号仅能注册 1 个 Zilliz Cloud 账号**）→ ⑤ 点「获取验证码」填入短信验证码 → ⑥ 勾选同意使用条款和隐私政策 → ⑦ 点「注册」→ ⑧ 在弹窗中再次输入邮箱验证码并点「验证」。首次用邮箱密码登录后需完成一份问卷。控制台会话闲置 6 小时过期。
  URL: https://docs.zilliz.com.cn/docs/register-with-zilliz-cloud
- 注册后系统**自动创建 1 个组织**（每人/组织默认只能有 1 个组织，需要更多须提工单）；每个组织最多 100 个项目。
  URL: https://docs.zilliz.com.cn/docs/limits

**创建 Serverless 集群**

- 前置条件：已注册账号；在目标组织/项目中有集群创建权限。
  URL: https://docs.zilliz.com.cn/docs/create-pay-as-you-go-cluster
- 创建方式：在 Zilliz Cloud Web 控制台创建（也可用 RESTful API）。集群状态变为**运行中（Running）**即创建成功。
  URL: https://docs.zilliz.com.cn/docs/create-pay-as-you-go-cluster , https://docs.zilliz.com/docs/free-and-serverless-clusters
- **创建过程中必须保存集群访问凭证（用户名 + 密码），该信息只展示一次**（官方原文：「集群创建过程中，请保存集群访问凭证（用户名和密码）。该信息将仅展示一次。」）。
  URL: https://docs.zilliz.com.cn/docs/create-pay-as-you-go-cluster
- 用 RESTful API 创建 Serverless 集群：`POST https://api.cloud.zilliz.com/v2/clusters/createServerless`，body 需 `clusterName` / `projectId` / `regionId`。
  URL: https://docs.zilliz.com/docs/free-and-serverless-clusters
- 数量限制：未绑定支付方式时，最多免费试用 1 个 Serverless 或 Dedicated 集群；绑定支付方式后每项目最多 100 个 Serverless 集群。
  URL: https://docs.zilliz.com.cn/docs/limits
- 免费额度：首次用企业邮箱注册赠送 **¥300 优惠券，有效期 30 天**，可用于 Serverless 和按量计费 Dedicated；若绑定云市场支付方式，有效期延长至 **1 年**。
  URL: https://docs.zilliz.com.cn/docs/free-trials

**取 URI（Endpoint）和 Token**

- **Endpoint**：控制台 → 目标集群的**集群详情**页 → 在**连接信息**卡片（国际站叫 **Connect** 卡片）上复制「公共 Endpoint」。
  URL（中国站）: https://docs.zilliz.com.cn/docs/connect-to-clusters
  URL（国际站）: https://docs.zilliz.com/docs/connect-to-serving-cluster
- **Free / Serverless 的 Endpoint 格式（官方给出）**：`https://{cluster-id}.serverless.{region}.vectordb.zillizcloud.com`，**不带端口**（Dedicated 才是 `https://{cluster-id}.{region}.vectordb.zillizcloud.com:19530`）。
  URL: https://docs.zilliz.com/docs/connect-to-serving-cluster
  ⚠️ 中国区（华东1 杭州）的完整域名后缀（是否为 `.zillizcloud.com.cn`）在官方文档中**未找到**明文示例，以控制台「连接信息」卡片实际显示为准。
- **Token**：两种等价方式 —— ① **API 密钥**（Organization → **API Keys** 页创建，仅 Organization Owner 和 Project Admin 可创建；密钥名称 ≤64 字符，可勾选「Restrict Access to Specific Clusters and Volumes」限制可访问集群；生产环境官方建议用 customized key 而非 personal key）；② **集群凭证**，格式为 `username:password`。
  URL（API 密钥）: https://docs.zilliz.com/docs/manage-api-keys
  URL（Token 说明）: https://docs.zilliz.com.cn/docs/connect-to-clusters
- 连接示例（Python）：`MilvusClient(uri=CLUSTER_ENDPOINT, token=TOKEN)`；验证方式：`client.list_collections()`。
  URL: https://docs.zilliz.com.cn/docs/connect-to-clusters

---

## 2. 功能支持（最关键）

先说结论：**9 项中 8 项明确支持，1 项有 Serverless 专属例外。** Zilliz Cloud 有一份官方的 API/功能可用性矩阵，含独立的 Serverless 列。

- **官方功能矩阵存在**：https://docs.zilliz.com/docs/api-comparison （标题 *API Availability*，表头为 `Category | API | Console | Free | Serverless | Dedicated/BYOC`）
  ⚠️ 中国站的对应页 https://docs.zilliz.com.cn/docs/api-comparison **没有 Serverless 列**（只有「GUI 操作」和「企业版/BYOC」两列），所以中国站读者看不到这些限制。
- **不存在** `/docs/serverless-limitations` 页面：https://docs.zilliz.com/docs/serverless-limitations 与 https://docs.zilliz.com.cn/docs/serverless-limitations 均 404。
- **Serverless 运行的 Milvus 版本：未找到**明确声明。可核实的是：flush 限流条款写明适用于「兼容 Milvus v2.4.x 或更高版本的 Serverless 集群」；官方变更日志显示 Milvus v2.5.x 于 2025-01-27 进入 Zilliz Cloud、v2.6.x 公测 2025-10-09、**v2.6.x GA 2025-12-26**，且创建集群时不能指定 Milvus 版本，平台自动使用最新支持版本。
  URL: https://docs.zilliz.com.cn/docs/changelogs

逐条结论：

| # | 能力 | 结论 | 证据（URL） |
|---|---|---|---|
| 1 | 稀疏向量字段 `SPARSE_FLOAT_VECTOR` | **支持** | 官方 Schema 示例 `datatype=DataType.SPARSE_FLOAT_VECTOR`（稀疏向量字段无需 dim）：https://docs.zilliz.com/docs/use-sparse-vector , https://docs.zilliz.com/docs/full-text-search 。**Serverless 专属声明：未找到**（文档按「Zilliz Cloud 整体」编写，不按部署方式打标） |
| 2 | BM25 Function（`FunctionType.BM25`，从文本字段自动生成稀疏向量） | **支持** | `Function(name="text_bm25_emb", input_field_names=["text"], output_field_names=["sparse"], function_type=FunctionType.BM25)`，源 VARCHAR 字段需 `enable_analyzer=True`；索引 `metric_type="BM25"`，可调 `bm25_k1`(1.2–2.0) / `bm25_b`：https://docs.zilliz.com/docs/bm25-function , https://docs.zilliz.com/docs/full-text-search 。**Serverless 专属声明：未找到** |
| 3 | 全文检索 / `TEXT_MATCH` / `PHRASE_MATCH` | **支持**（两者都有独立文档页） | `TEXT_MATCH(field_name, text)`，需 `enable_analyzer=True` 且 `enable_match=True`，另有 `TEXT_MATCH_FUZZY(..., max_edit_distance=1)`：https://docs.zilliz.com/docs/text-match 。`PHRASE_MATCH(field_name, phrase, slop)`，大小写不敏感：https://docs.zilliz.com/docs/phrase-match 。中国站同页存在：https://docs.zilliz.com.cn/docs/text-match , https://docs.zilliz.com.cn/docs/phrase-match 。**均无 Serverless 限制说明** |
| 4 | `hybrid_search()` + `RRFRanker` | **支持** | `client.hybrid_search(collection_name="my_collection", reqs=reqs, ranker=ranker, limit=2)`：https://docs.zilliz.com/docs/hybrid-search 。RRF Ranker：https://docs.zilliz.com/docs/reranking-rrf ；Weighted Ranker：https://docs.zilliz.com/docs/reranking-weighted-reranker 。⚠️**文档缺陷提醒**：API 参考页 https://docs.zilliz.com/reference/python/python/Vector-hybrid_search 开头写「This method applies only to dedicated serving clusters and on-demand compute」，但同一段下方又列出 Free & Serverless 的 endpoint；该句在 `search()` 参考页（https://docs.zilliz.com/reference/python/python/Vector-search）中**逐字相同**，而 `search()` 在功能矩阵中是 Serverless ✔︎ —— 说明这是「serving 集群 vs 按需计算」的模板残留措辞，**不是** Serverless 排除项 |
| 5 | 自定义 Analyzer（分词器） | **支持**（有一处缺口） | Analyzer = 1 个 tokenizer + 若干 filter；内置 `standard`/`english`/`chinese`，`enable_analyzer`/`enable_match`/`run_analyzer()`：https://docs.zilliz.com/docs/analyzer-overview 。可用分词器：`standard`、`whitespace`、`jieba`（中文）、`lindera`（日/韩）、`icu`、`language-identifier`；过滤器 `lowercase`/`asciifolding`/`alphanumonly`/`cnalphanumonly`/`cncharonly`/`pinyin`/`stop`/`length`/`stemmer`。中国站另增 `thai-tokenizer`/`thai-analyzer`/`arabic-analyzer`。**`ngram` 分词器：未找到**（`ngram-tokenizer`/`ngram-filter` 均 404；`ngram` 只作为**索引类型**存在：https://docs.zilliz.com/docs/ngram-index-type ）。⚠️「自定义词典与分词器（Custom dictionaries and tokenizers）」被列为 **Milvus 3.0.x / 仅按需计算** 功能，而「Serving 集群尚不支持」→ **Serverless 不可用**：https://docs.zilliz.com.cn/docs/changelogs |
| 6 | 标量字段过滤，含 `ARRAY` 数组类型的 `ARRAY_CONTAINS_ANY` | **支持** | ARRAY 类型：https://docs.zilliz.com/docs/use-array-fields 。ARRAY 操作符表含 `ARRAY_CONTAINS`/`ARRAY_CONTAINS_ALL`/`ARRAY_CONTAINS_ANY`/`ARRAY_LENGTH`：https://docs.zilliz.com/docs/array-filtering-operators ，中国站：https://docs.zilliz.com.cn/docs/array-filtering-operators 。**Serverless 专属限制：未找到** |
| 7 | nullable 字段（可空字段） | **标量字段支持；向量字段也支持；但 Serverless 的 nullable StructArray 不支持** | `nullable` 是 schema 级字段属性，**标量与向量字段均支持**：https://docs.zilliz.com/docs/nullable-fields 。`default_value` 仅标量字段支持（主键/向量不支持，JSON 与 ARRAY 不支持默认值）；`nullable` 创建后不可修改；nullable 字段不能做 partition key；可空向量字段不支持 `IS NULL`/`IS NOT NULL` 过滤：同页。⚠️**明确的 Serverless 排除**：原文「On Zilliz Cloud, nullable StructArray fields are supported on On-Demand Clusters running Milvus 3.0.0 or later... **Serving Clusters do not support nullable StructArray fields.**」—— Serverless 属于 serving 集群，故**不支持** |
| 8 | `upsert` / `delete`（按主键、按表达式） | **支持** | `upsert()` 在功能矩阵中 Serverless = ✔︎：https://docs.zilliz.com/docs/api-comparison 。两种删除模式均有独立章节（按过滤条件 / 按主键 IDs）：https://docs.zilliz.com/docs/delete-entities 。upsert 支持 `partial_update=True`：https://docs.zilliz.com/docs/upsert-entities 。⚠️注意：`bulkInsert()` API 在**所有档位**都是 ✘（含 Serverless），批量导入应走 **Import 接口**：https://docs.zilliz.com/docs/api-comparison |
| 9 | 多向量字段 | **支持，Serverless 上限 4 个** | 「Vector fields per collection — Free & Serverless: **4**；Dedicated: 10」（每集合字段总数上限 64）：https://docs.zilliz.com/docs/limits , 中国站：https://docs.zilliz.com.cn/docs/limits 。官方 hybrid-search 页给出单 schema 内 3 个向量字段（text_dense 768 / text_sparse / image_dense 512）的可运行示例：https://docs.zilliz.com/docs/hybrid-search |

**Serverless 明确不支持的其他项（来自官方功能矩阵，本次已逐行核对原文）**

- 多 Database：`CreateDatabase` / `DropDatabase` / `ListDatabases` → Serverless ✘（Dedicated ✔）
  ⚠️ 若你的 Milvus 集合位于非 default 的 database 中，迁移时需注意 Serverless 不能建库。
- `manualCompact()`（手动合并）→ Serverless ✘
- 集群级 RBAC：`createRole` / `dropRole` / `addUserToRole` / `removeUserFromRole` / `selectRole` / `selectUser` / `selectGrantForRole` / `selectGrantForRoleAndObject` / `grantPrivilegeV2` / `revokePrivilegeV2` → 全部 Serverless ✘
- Serverless ✔︎ 的关键项：`createCollection` / `dropCollection` / `insert` / `upsert` / `search` / `query` / `createIndex` / `dropIndex` / `describeIndex` / `createPartition` / `dropPartition` / `loadCollection` / `releaseCollection` / `createAlias` / `getCompactionState`
- 全档位都 ✘（非 Serverless 专属）：`bulkInsert()`、`getFlushState()`、`getMetrics()`、`loadBalance()`、`getReplicas()`、`alterAlias()`
  URL: https://docs.zilliz.com/docs/api-comparison
- Milvus 3.0.x 全部能力**仅按需计算集群可用**，Serving 集群（含 Serverless）尚不支持
  URL: https://docs.zilliz.com.cn/docs/changelogs

---

## 3. 容量与配额限制

**关于「是否有 100 万行之类的行数上限」—— 没有。官方原文：`Serverless clusters in Zilliz Cloud have no capacity limits.`**
URL: https://docs.zilliz.com/docs/limits （中国站同表：https://docs.zilliz.com.cn/docs/limits ）
「100 万」这个数字来自 **Free 集群**的 5 GB 存储 ≈ 100 万个 768 维向量，**不是 Serverless 的限制**。

逐条：

| 项目 | Serverless 限制 | URL |
|---|---|---|
| **单集合最大行数** | **无硬性容量限制**（原文：Serverless clusters in Zilliz Cloud have no capacity limits） | https://docs.zilliz.com/docs/limits |
| **最大集合数** | **每个 Serverless 集群 100 个 Collection**（每个项目最多 100 个 Serverless 集群；Free 仅 5 个 Collection） | https://docs.zilliz.com/docs/limits |
| **每个集合字段数** | 64 个字段，其中**向量字段 4 个** | https://docs.zilliz.com/docs/limits |
| **最大向量维度** | **32,768** | https://docs.zilliz.com/docs/limits |
| **Shard 数** | **2**（不可调） | https://docs.zilliz.com/docs/limits |
| **单 Partition 写入量** | 2 TB | https://docs.zilliz.com/docs/limits |
| **QPS / 并发上限** | **未找到**任何以「QPS」为单位的 Serverless 数值上限。官方只公布操作级速率限制（见下）。定价页给出的 500–1500 / 100–300 QPS 是 **Dedicated** 的性能型/容量型指标，不适用于 Serverless。 | https://docs.zilliz.com/docs/limits , https://zilliz.com.cn/pricing |
| **单次查询最大 limit（topK）** | **Free & Serverless：topK ≤ 1,024 个实体**（Dedicated 为 16,384）。Query 响应上限为 16,384 个实体。另有：每个 search 请求/响应 ≤ **64 MB**；单次 search 携带的查询向量 **nq ≤ 10**（Dedicated 为 16,384）。Collection 级「大 Top-K」功能可把启用集合的最大返回实体数从 16,384 扩展到 1,000,000（属于 Vector Lakebase 公测能力，是否覆盖既有 Serverless 集合未明确）。 | https://docs.zilliz.com/docs/limits , https://docs.zilliz.com.cn/docs/use-large-topk , https://docs.zilliz.com.cn/docs/changelogs |
| **单次插入批量大小限制** | Serverless 的 insert/upsert 速率上限为 **10 MB/s**（Free 2 MB/s；Dedicated 16 MB/s + 1 MB/s×CU，最高 256 MB/s）；**单 shard 写入速率 ≤ 32 MB/s**。文档未给出单次请求的条数上限，但 search/query/delete 请求/响应均 ≤ 64 MB。 | https://docs.zilliz.com/docs/limits |
| **数据导入（Import）上限** | Serverless：单次导入**总量 ≤ 1 TB**、**单文件 ≤ 10 GB**、**文件数 ≤ 1,000**；单 Collection 最多 **10,000** 个运行中/待运行的导入任务 | https://docs.zilliz.com/docs/limits |
| DDL 速率限制 | Collection 操作（创建/加载/释放/删除）20 req/s；Partition 操作 20 req/s | https://docs.zilliz.com/docs/limits |
| Load / Flush / Delete 速率 | Load 20 req/s；Flush 0.1 req/s（适用于兼容 Milvus v2.4.x+ 的 Serverless 集群）；Delete 0.5 MB/s per cluster | https://docs.zilliz.com/docs/limits |
| 迁移 | 每次迁移最多 10 个 Collection（Serverless/Dedicated） | https://docs.zilliz.com/docs/limits |

**对本项目的判断**：160 万行 / 1024 维 **远低于**任何 Serverless 容量门槛（无容量上限、维度上限 32768、字段够用）。真正的约束是 **topK ≤ 1024**、**nq ≤ 10**、**写入 10 MB/s** 和 **2 个 shard**——而不是行数。

---

## 4. 计费细节

**vCU 是什么 / 怎么消耗**

- 定义（原文）：「vCU 是用于衡量读取（如 search、query）和写入操作（如 insert、upsert、delete）所消耗资源的基本单位。vCU 的概念**仅针对 Free 和 Serverless 集群**。」
  URL: https://docs.zilliz.com.cn/docs/limits , https://docs.zilliz.com/docs/limits
- 计费公式（官方）：
  `向量数据库费用（写入） = vCU 单价 × 写入 vCU 用量`
  `向量数据库费用（读取） = vCU 单价 × 读取 vCU 用量`
  总费用 = 读取 + 写入 + 存储 + 其他（数据传输等）
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost
- **vCU 单价：¥21 / 百万 vCU**（中国区列表价，读写同价）
  URL: https://zilliz.com.cn/pricing/pricing-guide （章节「向量数据库（Serverless）」）
- 计费按**操作**计：读取 = search / hybrid search / query；写入 = insert / upsert / delete。**Collection load 与后台索引构建不产生 vCU 费用**（官方计费项穷举中未列，属「以未列证不存在」，非明文声明）。
- 写入 vCU 用量细则（官方）：
  - `Insert`：**1 KB 插入数据 = 0.25 vCU**
  - `Delete`：**删除 1 个 Entity = 1 vCU**；**删除 1 个不存在的 Entity 也消耗 1 vCU**
  - `Upsert`：按更新的数据量 + 删除的 Entity 数量计算
  - **Import 和 bulk insert 操作不产生写入费用**（官方原文）
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost
- 读取 vCU 用量由 3 个因素决定：① 请求次数；② **单次请求扫描的数据量 —— 每次读取请求 Zilliz Cloud 会扫描整个 Collection**（用 Partition Key 可减少扫描量）；③ 返回的数据量（返回全部字段含向量的请求远贵于只返回 ID）。
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost

**一次检索大约消耗多少 vCU —— 有公开估算方法与示例**

- 官方明确下限：**「每次读取操作最低会消耗 6 vCU」**
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost
- 官方聚合估算表（针对不同规模数据做 **100 万次读取操作**的 vCU 用量与费用，不含标量）：

  | 数据量 | 读取 vCU 用量 | 读取费用 |
  |---|---|---|
  | 100 万 × 128 维 | 5 百万 | ¥105 |
  | 100 万 × 768 维 | 15 百万 | ¥315 |
  | 500 万 × 768 维 | 35 百万 | ¥735 |
  | 1000 万 × 768 维 | 55 百万 | ¥1155 |
  | 100 万 × 1536 维 | 25 百万 | ¥525 |
  | 1000 万 × 1536 维 | 75 百万 | ¥1575 |
  | 1 亿 × 1536 维 | 290 百万 | ¥6090 |
  | 100 亿 × 1536 维 | 1495 百万 | ¥31395 |
  | 100 万 × 2560 维 | 30 百万 | ¥630 |

  官方提示：规模从 100 万增长到 1000 万甚至 1 亿时，vCU 用量**并非线性 10 倍增长**；建议实测。
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost
- 写入估算表（官方）：

  | 数据量 | 写入 vCU 用量 | 写入费用 |
  |---|---|---|
  | 100 万 × 128 维 | 0.125 百万 | ¥2.625 |
  | 100 万 × 768 维 | 0.75 百万 | ¥15.75 |
  | 100 万 × 1536 维 | 1.5 百万 | ¥31.5 |
  | 100 万 × 2560 维 | 2.5 百万 | ¥52.5 |

  （多向量字段时写入费用线性增长）
  URL: https://docs.zilliz.com.cn/docs/serverless-cluster-cost
- **官方估算工具**：价格计算器 https://zilliz.com.cn/pricing#calculator （Serverless 页签，输入 Entity 数量 / 向量维度 / QPS 得到月成本）。专门的「vCU 计算器」文档页：**未找到**。
  URL: https://zilliz.com.cn/pricing , https://docs.zilliz.com.cn/docs/faq-resource-planning

**→ 针对本项目的推算（注意：1024 维无官方数据点，以下是我们按官方锚点做的线性内插，属推算而非官方数字）**

- 向量裸数据量：1,600,000 × 1024 × 4 B ≈ **6.55 GB**（不含主键与标量）
- **写入费用**：若走普通 `insert`，按 1 KB = 0.25 vCU → 6,553,600 KB × 0.25 ≈ **1.64 百万 vCU ≈ ¥34**（标量另计）。**若改用 Import 接口批量导入，写入费用为 ¥0**（官方明文：Import 和 bulk insert 不产生写入费用）。这是本项目最直接的一个省钱点。
- **读取费用**：官方无 1024 维数据点。768 维是 15 百万 vCU/百万次读取、1536 维是 25 百万，1024 维按线性内插 ≈ **18–20 百万 vCU / 百万次读取 ≈ ¥380–¥420 / 百万次读取**（160 万行规模会比 100 万行略高，且返回字段越多越贵）。每次读取的下限是 6 vCU。
- **存储费用**：6.55 GB × ¥1.2/GB/月 ≈ **¥7.9/月**（仅向量裸数据；标量、索引占用未计入）

**存储 ¥1.2/GB/月 是否包含索引？**

- 价格确认：中国区列表价「存储（Serverless） **¥1.2 / GB / 月**」，**按小时计费**（每小时费用 = 每月费用 / 30 / 24）。对比：Dedicated ¥0.5/GB/月、Database ¥0.5、备份 ¥0.5 —— Serverless 存储单价是 Dedicated 的 2.4 倍。
  URL: https://zilliz.com.cn/pricing/pricing-guide
- 存储计费公式：`存储费用 = 存储单价 × 数据量 × 存储时长`，数据量 = 存储的所有数据或备份文件大小。
  URL: https://docs.zilliz.com.cn/docs/storage-cost
- **「是否包含索引」：未找到明文说明。** 可核实的间接证据：① 中国区列表价中**不存在任何独立的「索引存储」计费项**（只有 存储(Dedicated)/存储(Serverless)/存储(Database)/备份/Volume/存储请求次数），因此索引存储**没有单独收费**；② 文档对 Serverless 存储的定义仅为「存储在您的 Serverless cluster 中的**数据**」，而「数据和索引」这种明确措辞只出现在 Database/Managed Collection 条目下（原文：Managed Collection 中的数据和索引）。**「Serverless 的 ¥1.2 计费量里是否把索引字节数也算进去」这一点官方没有写清楚，属未找到。**
  URL: https://zilliz.com.cn/pricing/pricing-guide , https://docs.zilliz.com.cn/docs/storage-cost

**挂起（suspend）后是否停收计算费？—— 前提有误：Serverless 集群根本不能挂起**

- 计费规则本身（针对可挂起的集群）：「集群挂起后将暂停收取向量数据库费用，但会继续产生存储费用」；「创建中、挂起中、恢复运行中、已挂起状态下，不收取向量数据库费用。但存储费用仍会产生。」
  URL: https://zilliz.com.cn/pricing/pricing-guide , https://docs.zilliz.com.cn/docs/storage-cost
- **但**：中国站官方原文「**Serverless 集群不支持挂起和恢复运行的操作。**」；国际站对应表格中 Serverless 行同样写明「Serverless clusters do not support suspend and resume operations.」只有 Dedicated 可手动挂起；Free 集群连续 7 天不活跃后自动挂起、可随时恢复。
  URL: https://docs.zilliz.com.cn/docs/manage-cluster , https://docs.zilliz.com/docs/free-and-serverless-clusters
- 因此对 Serverless 的正确理解是：**它本来就是纯按用量（vCU）计费、没有常驻计算费，空闲时计算费天然为 0；无需也无法通过「挂起」来省计算费。存储费只要数据还在就一直在收。**
- 官方关于「避免未使用集群产生费用」的建议（针对可挂起集群）：「建议您挂起未使用的集群以节省成本」；免费试用文档也建议「为节省优惠券，我们建议您手动挂起未使用的集群」——这两句只对 Dedicated 有效。
  URL: https://docs.zilliz.com.cn/docs/faq-resource-planning , https://docs.zilliz.com.cn/docs/free-trials

**其他计费要点**

- 数据传输：前 100 GB 免费；中国内地公网出口 ¥0.8/GB；同地域 ¥0/GB；**通过 Private Endpoint 发起的操作不收费（¥0）**
  URL: https://zilliz.com.cn/pricing/pricing-guide
- 存储请求次数：Class 1 / Class 2 各 ¥10 / 百万次请求（主要用于按需计算索引构建、分层存储冷数据读取、Volume 读写）
  URL: https://zilliz.com.cn/pricing/pricing-guide
- Serverless 的 vCU 月度额度为「无（N/A）」，即**不封顶、也没有免费月度额度**；Free 集群才有每月 250 万免费 vCU。
  URL: https://docs.zilliz.com/docs/limits , https://docs.zilliz.com.cn/docs/free-trials
- 未找到：vCU/秒上限、突发（burst）额度、以及基于 vCU 的限流（429）行为说明。

---

## 5. 地域

**是的，中国区 Serverless 只能在阿里云华东1（杭州）。** 已核实。

- 官方「部署方式支持」表：**SaaS（Free 和 Serverless）** 在**阿里云**下标注为「ℹ️ **部分地域：华东1（杭州）**」；在**腾讯云**和**亚马逊云科技**两列均为 ✘（不支持）。作为对比，「SaaS（Dedicated）」和「BYOC」在阿里云/腾讯云/AWS 均为「✔︎ 全部地域」。
  URL: https://docs.zilliz.com.cn/docs/cloud-providers-and-regions
- 阿里云在 Zilliz Cloud 中国站支持的**地域列表**（供对比，但列表本身不区分部署方式）：中国内地 = 华东1（杭州）、华东2（上海）、华北2（北京）、华南1（深圳）；另有美国（弗吉尼亚）、新加坡、沙特（利雅得-合作伙伴运营）。腾讯云：华北地区（北京）、华东地区（上海）、美国东部（弗吉尼亚）。亚马逊云科技：中国（宁夏）。—— **这些地域上 Serverless 均不可用**，只有杭州可以。
  URL: https://docs.zilliz.com.cn/docs/cloud-providers-and-regions
- 注意事项同一页写明：「云地域支持情况可能因**工作负载类型、部署选项**和功能而异。创建项目前，请根据本文选择合适的云地域。」—— 即 Serverless 的地域可用性确实比 Dedicated 窄。
  URL: https://docs.zilliz.com.cn/docs/cloud-providers-and-regions
- 成本影响：**项目下所有资源必须部署在同一云地域**（「同一项目下所有资源都部署在同一云地域中」），所以要建 Serverless 就得选杭州项目。
  URL: https://docs.zilliz.com.cn/docs/manage-projects
- 数据传输：同地域 ¥0/GB；中国内地↔北美/亚太跨地域 ¥5.6/GB。若你的应用不在杭州/华东，跨地域或公网出口流量会产生费用（中国内地公网出口 ¥0.8/GB，前 100 GB 免费）。
  URL: https://zilliz.com.cn/pricing/pricing-guide

---

## 最关键的 3 条发现

1. **Serverless 没有 100 万行之类的行数上限 —— 官方明文「Serverless clusters in Zilliz Cloud have no capacity limits」。「100 万」是 Free 集群的额度（5 GB ≈ 100 万×768 维），不是 Serverless 的。** 160 万×1024 维在这个集群上容量完全不是问题（维度上限 32,768）。真正的硬约束是另外三个：**单次 search 的 topK ≤ 1,024、nq ≤ 10、写入速率 10 MB/s**，以及 **2 个 shard、最多 100 个 Collection**。
   https://docs.zilliz.com/docs/limits , https://docs.zilliz.com.cn/docs/limits

2. **功能上 Serverless 完全够用 —— 稀疏向量、BM25 Function、TEXT_MATCH/PHRASE_MATCH、hybrid_search+RRFRanker、自定义 Analyzer、ARRAY_CONTAINS_ANY、nullable、upsert/delete、多向量（上限 4）全部支持**，官方有一份带独立 Serverless 列的功能矩阵。唯二要小心的：(a) **nullable StructArray 在 serving 集群（含 Serverless）不支持**；(b) Serverless **不能建 Database**（`CreateDatabase`/`ListDatabases` ✘）—— 如果你的 160 万行集合在非 default 的 database 里，迁移要改结构；另外 `bulkInsert()` 在所有档位都是 ✘，批量导入必须走 **Import 接口**。⚠️ 中国站的功能矩阵页**缺少 Serverless 列**，只看中国站会漏掉这些限制。
   https://docs.zilliz.com/docs/api-comparison , https://docs.zilliz.com/docs/nullable-fields

3. **费用极低，而且「挂起」这个前提不成立 —— Serverless 集群压根不支持挂起/恢复；它本来就是按 vCU 用量的纯按需计费，空闲时计算费天然为 0。** 成本量级：**Import 批量导入不产生写入费用（¥0）**；存储 6.55 GB × ¥1.2/GB/月 ≈ **¥7.9/月**；读取按官方锚点内插，1024 维约 **¥380–420 / 百万次检索**（官方下限 6 vCU/次），且**每次读取都会扫描整个集合**——用 Partition Key 可显著降低读取 vCU。注册赠 ¥300 优惠券（30 天，绑定云市场支付可延至 1 年）足够覆盖试用期。注意 Serverless 存储单价 ¥1.2/GB/月是 Dedicated ¥0.5 的 2.4 倍，且**价格表中没有独立索引存储计费项**（索引是否计入 ¥1.2 的计量口径官方未写明）。
   https://docs.zilliz.com.cn/docs/serverless-cluster-cost , https://zilliz.com.cn/pricing/pricing-guide , https://docs.zilliz.com.cn/docs/manage-cluster

---

## 明确「未找到」的项（不要当成事实使用）

- Serverless 具体运行的 Milvus 版本号（只知道「兼容 v2.4.x 或更高」，平台自动升级，创建时不可指定）
- Serverless 的 QPS / 并发数值上限（官方只给操作级速率限制）
- 中国区 Serverless Endpoint 的完整域名后缀示例（是否 `.zillizcloud.com.cn`）—— 以控制台「连接信息」卡片为准
- 「Serverless 存储 ¥1.2/GB/月 是否把索引字节计入计量口径」的明文说明
- vCU/秒上限、突发额度、基于 vCU 的限流（429）行为
- 除官方聚合估算表之外的 vCU/次检索数据（无官方博客给出更细的数字）
- 1024 维向量的官方 vCU 估算数据点（报告中的 ¥380–420/百万次是我们按 768/1536 维锚点做的内插推算，非官方数字）
