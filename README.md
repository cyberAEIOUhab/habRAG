# habRAG

**奥匈帝国史研究助手** —— 一个面向哈布斯堡 / 奥匈帝国史的 RAG 研究工具。

对 **190 种文献、16 万个片段**（英文 / 德文 / 波兰文 / 中文）做混合检索，
由大模型给出**带可核验引用的回答**，并支持对一份现成长文逐论点核查。

它不是"把 PDF 丢进去问问题"的通用 RAG —— 它是为一手档案与德语学术文献的**引证严谨性**设计的。

---

## 它解决什么问题

历史研究里，让大模型总结材料很容易，难的是**每句话都能回溯到具体出处，且出处经得起查**。本项目围绕这一点做了四件事：

| | 做法 |
|---|---|
| **混合检索** | 向量语义检索 **+** 词法检索（云端 BM25 / 本地 FTS5 trigram）经 RRF 融合后再精排。两者互补：在 12 个领域术语上，词法腿召回 100%、向量腿仅 44% |
| **两类引用格式** | 二手文献 `(作者, 年份, p. 页码)`，一手档案 `ÖUA VIII, Nr. 10364` —— 后者按卷次 + 文件号定位，可逐条核对 |
| **引用核验** | 每次回答后由模型回查：哪些片段真被用到、哪些引用疑似编造、引用与片段的对照关系 |
| **台账式长文核查** | 给一篇现成文章，先拆成可核查论点清单，再逐论点独立检索取证、提交裁决（含证据等级），最后综合成报告 |

## 三种问答模式

- **普通模式** —— 单次检索 + 流式生成。支持「继续对话（不重新检索）」复用上一轮候选池
- **深度分析模式** —— agent 自主工具循环，最多 50 次工具调用；模型可自主管理检索进度
- **长文本分析模式** —— 三阶段台账式核查，每个论点独立小循环、独立裁决

## 六个工具

`search_corpus`（带六维元数据过滤）· `expand_chunk`（取相邻片段还原上下文）·
`get_book_info` · `list_sources_on_topic`（只返回书目，不返回正文）·
`list_books_by_filter`（纯结构化，不做语义检索）·
**`exclude_chunks`**（把不相关片段加入会话级排除集，**不占检索名额** —— 让模型自己解决"检索结果被同一本书挤满"的问题）

部分约束是**程序化硬约束**而非提示词：问题锁定单本书时强制覆盖模型传参、越界取片段直接拒绝、侧栏过滤条件硬覆盖模型参数。

---

## 架构

```
Streamlit UI (app.py + pages/)
        │
        ├── 检索链路 (corpus_lib.py)
        │     查询改写 → 向量腿 + 词法腿 → RRF(k=60) → 跨查询融合 → 精排
        │
        ├── 向量库
        │     Zilliz Cloud Serverless（生产，阿里云杭州）
        │     或 本地 ChromaDB（BACKEND="chroma"，可离线/回滚）
        │
        └── 模型
              DeepSeek（查询改写 / 回答 / 引用核验）
              SiliconFlow bge-m3（1024 维向量）+ bge-reranker-v2-m3（精排）
              智谱 GLM（light 模式的排版修正）
```

**后端可切换**：`config.py` 里一个 `BACKEND` 变量在云端与本地之间切换，切换后
检索、浏览、入库、管理全部功能一致 —— 适配器（`milvus_backend.py`）把 Milvus
包装成与 Chroma 相同的接口。

---

## 语料现状

| 项 | 值 |
|---|---|
| 片段总数 | **160,475** |
| 文献种数 | 190（`bookdata.json` 中 192 条，其中 2 种无文字层） |
| 语言 | 英文 72.4% · 德文 26.0% · 混合 1.0% · 波兰文 0.7% |
| 来源类型 | 二手研究 75.7% · **一手档案 21.6%** · 混合 2.7% |
| 一手档案 | ÖUA（《奥匈外交政策》8 卷）· MRP（《奥地利大臣会议记录》33 卷）· Conrad 回忆录 5 卷 |
| 每片段 | 中位 204 词；带页码 85.3%，带档案号 13.1% |

---

## 快速开始

### 1. 取得代码与密钥

```powershell
git clone <仓库地址>
cd habRAG
Copy-Item .env.example .env
notepad .env          # 填入 DeepSeek / SiliconFlow / GLM / Zilliz 的密钥
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt

# ★ 云端向量库客户端必须装到项目内的 _libs/，不要全局安装
pip install pymilvus --target=.\_libs -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> ⚠️ **不要全局 `pip install pymilvus`**：它会连带把 `protobuf` 升到 7.x、`pandas` 升到 3.x，
> 而 Streamlit 1.50 要求 `protobuf<7`、`pandas<3` —— 一装就把应用弄坏。
> 脚本会自动把 `_libs/` 加入 `sys.path`（追加到末尾，不遮蔽系统版本）。

### 3. 准备语料

**语料不入版本库**（原始书籍受版权保护，体积也大）。你有两条路：

- **连自己的云端集合** —— 在 `.env` 里填 `ZILLIZ_URI` 与 `ZILLIZ_TOKEN`
- **从原始素材本地入库** —— 把 PDF/EPUB 放进来源目录，改好 `ingest.py` 的 `SOURCE_DIR`，然后
  ```powershell
  python -X utf8 ingest.py
  ```

### 4. 运行

```powershell
streamlit run app.py                 # 主应用
streamlit run app.py -- -light       # Light 模式（轻量/免费模型）

python -X utf8 db_check.py           # 语料库一致性检查
python -X utf8 eval/run_eval.py      # 检索与回答质量评测
```

---

## 配置

所有配置集中在 `config.py`，**密钥全部来自 `.env`**（该文件已被 `.gitignore` 排除）。

优先级：**环境变量 > `.env` > 默认值**。启动自检会列出缺失的密钥及其影响的功能。

| 变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` | 查询改写、回答生成、引用核验 |
| `SILICONFLOW_API_KEY` | 向量嵌入、精排 |
| `GLM_API_KEY` | light 模式的排版修正（缺省不影响主流程） |
| `ZILLIZ_TOKEN` | 云端向量库连接 |
| `HABRAG_BACKEND` | `zilliz`（默认）/ `chroma` |
| `RERANK_ENABLED` / `QUERY_REWRITE_ENABLED` / `HYBRID_SEARCH_ENABLED` | 三个检索增强开关 |

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **项目全貌**：数据层构成、检索链路、应用层逻辑、入库链路、字段定义、外部依赖。写给"需要完整理解本项目的大语言模型" |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | 从本地 Chroma 迁移到 Zilliz Cloud 的完整记录：改动清单、切换与回滚、验证结果、API 踩坑、成本复盘 |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | 运维与扩容：备份、体检、排错速查、压测方法、全文腿改造路线 |
| [`reports/`](reports/) · [`zilliz-serverless-调研报告.md`](zilliz-serverless-调研报告.md) | 两份带官方 URL / 源码证据的原始调研 |

### 验证脚本

迁移与检索质量都可以独立复跑：

```powershell
python -X utf8 smoke_test.py          # 云集群能力探测（29 项）
python -X utf8 recall_test.py         # 小规模召回对比
python -X utf8 validate_zilliz.py     # 生产集合验证（召回基准 + 全部调用点 + 工具函数）
python -X utf8 test_adapter_write.py  # 适配器写入路径（12 项）
```

---

## 许可

- **代码**：[MIT](LICENSE)
- **数据**（`bookdata.json`、`metadata.json`）：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

本项目**不包含**受版权保护的书籍正文。语料库与含原文摘录的派生物（如 `textfix_cache.json`）
均在 `.gitignore` 中排除；引用规范中的书名、档案编号等书目信息属事实性数据。

---

## 已知限制

- **中文分词较粗**：云端分析器用 `icu` 分词器，中文按字切（`奥匈帝国` → `奥`/`匈`/`帝国`）。语料以英德文为主，中文查询主要依赖向量腿与查询改写
- **德语元音转写不完整**：`Hötzendorf` 与 `Hoetzendorf` 能互相匹配（靠 `stemmer(german)`），但词中 `oe`/`ue`/`ae` 的展开仍有限
- **单本全量取片段较慢**：云端取一本书全部片段（数千条）约 10–20 秒，界面上有 10 分钟缓存
