# habRAG —— 奥匈帝国史研究助手 · 项目全貌说明

> **本文档的用途**：把它发给任意大语言模型，使其无需接触代码库即可理解本项目的完整结构、数据构成与运行逻辑。
> 因此本文以"事实与结构"为主，不做评价、不列待办。
> **所有数字均为 2026-09-17 实测值**，非估算。

---

## 一、项目是什么

一个本地运行的 **RAG（检索增强生成）研究助手**，领域为**哈布斯堡 / 奥匈帝国史**。

- 界面：Streamlit 单页应用（含两个自动挂载的子页面）
- 向量库：本地 ChromaDB（持久化于 `db/`）
- 生成模型：DeepSeek（主任务）、智谱 GLM（轻量任务）
- 向量与精排模型：SiliconFlow 托管的 `BAAI/bge-m3`（1024 维）与 `BAAI/bge-reranker-v2-m3`
- 语料：**190 种文献、160,475 个片段**，涵盖英文、德文、波兰文、中文

**运行方式**

```bash
streamlit run app.py                 # 主应用（默认）
streamlit run app.py -- -light       # Light 模式（轻量模型）
python -X utf8 db_check.py           # 语料库一致性检查
python -X utf8 eval/run_eval.py      # 检索/回答质量评测
python -X utf8 ingest.py             # 原有入库脚本
python -X utf8 ingest_new.py         # 新增批次入库脚本
```

---

## 二、目录与文件清单

```
habRAG/
├── app.py                  2,252 行   Streamlit 主应用（三种问答模式）
├── corpus_lib.py             788 行   数据层 + 检索链路（无 Streamlit 依赖，可被脚本复用）
├── ingest.py                 517 行   原有入库脚本（136 本，按词数切分）
├── ingest_new.py             544 行   新增批次入库脚本（四套提取器）
├── config.py                  25 行   全部 API 配置与检索增强开关
├── db_check.py               177 行   三方一致性检查
├── clean.py                   17 行   一次性清理脚本（删除两本书的残留 chunk）
│
├── bookdata.json             192 条   书目元数据（权威来源）
├── metadata.json             192 条   内容级标签
├── book.json                 192 条   遗留文件（仅 title/language/description，代码中无引用）
├── textfix_cache.json        ✓       展示层排版修正缓存（键 = chunk_id 列表）
│
├── ingest_log.txt / ingest_processed.txt           原有入库的日志与断点状态
├── ingest_new_log.txt / ingest_new_processed.txt   新增批次的日志与断点状态
│
├── db/                      3.0 GB    ChromaDB 持久化目录
│   ├── chroma.sqlite3                2.37 GB（元数据 + FTS5 全文索引）
│   └── <uuid>/                       679 MB（HNSW 向量索引二进制）
│
├── pages/
│   ├── 1_语料浏览.py          156 行   按书目/章节/页码翻阅原始片段
│   └── 2_文献库管理.py        206 行   概览 / 一致性检查 / 单书重新入库与删除
│
├── eval/
│   ├── run_eval.py            391 行   评测脚本（retrieval / full 两种模式）
│   └── questions.json          12 题   种子题库
│
├── metadata/generate_metadata.py   711 行  生成 metadata.json 的脚本（LLM 逐章打标）
├── bookdata/                          建书目阶段的脚本与中间产物（历史归档）
└── sessions/                          对话持久化（index.json + 每会话一个 jsonl）
```

---

## 三、数据层的四个部分

### 3.1 `bookdata.json` —— 书目权威信息（192 条）

每条 16 个字段：

| 字段 | 说明 |
|---|---|
| `filename` | 源文件名（原始文献在 `D:\哈布斯堡史`） |
| `title` | **单一稳定书名，全系统的关联键**（ChromaDB 精确匹配、chunk_id 前缀均用它） |
| `author` / `year` / `publisher` / `language` / `page_count` | 书目项 |
| `is_scanned` / `has_bookmarks` / `bookmark_titles` | 载体特征 |
| `description` | 150–250 字中文简介 |
| `description_source` | `web_search` / `model_knowledge` / `not_found` |
| `extraction_confidence` | `high` / `medium` / `low` |
| `needs_review` / `extraction_notes` | 存疑标记与原因 |
| `priority_tier` | `standard` / `high` |

实测分布：`priority_tier` = standard 92 / high 100；`description_source` = web_search 168 / model_knowledge 24。

### 3.2 `metadata.json` —— 内容级标签（192 条）

与 bookdata 用同一个 `title` 作键，一一对应。两种粒度：

- **book 级（147 条）**：`{title, stance, granularity:"book", subfield[], period, region[], source_type}`
- **chapter 级（45 条）**：`{title, stance, granularity:"chapter", chapters:[{chapter_title, start_page, end_page, subfield[], period, region[], source_type}]}`

`ingest.py` 用 chunk 的 `page_num` 去匹配 chapter 的 `[start_page, end_page]`，逐 chunk 分配标签；匹配不到时退化为该书全部章节的聚合值。

**枚举取值**：

- `stance`：`衰落论` / `修正主义` / `中立描述` / `不涉及该争论`（衡量的是**对"哈布斯堡衰落论"的立场**，不是对一战责任的立场）
- `subfield`：`政治史` `外交史` `经济史` `军事史` `社会史` `民族史` `地区研究` `犹太史`
- `source_type`：`primary` / `secondary` / `mixed`
- `region`：30 个取值，涵盖帝国各王冠领地与周边列强
- `period`：`YYYY` 或 `YYYY-YYYY`

### 3.3 `book.json` —— 遗留文件（192 条）

仅 `{title, language, description}` 三字段，内容与 bookdata 一致。**代码中无任何引用**，不参与任何逻辑。

### 3.4 ChromaDB

- 路径：`db/`，collection 名 `habsburg`，向量维度 **1024**，距离度量 L2
- 表结构：`embeddings`（向量）+ `embedding_metadata`（标量元数据）+ `embedding_metadata_array`（数组元数据）+ `embedding_fulltext_search`（FTS5 全文索引，trigram 分词器）
- **`corpus_lib.fulltext_query` 直接以只读方式查询该 sqlite 的 FTS5 表**（`file:...?mode=ro`），这是全文检索腿的实现方式
- 该函数有两个必须保留的细节：
  1. **查询串先做 FTS5 语法清洗**——`re.sub(r"[^\w]+", " ", q)`。FTS5 把 `. , - / ( ) * :` 等视为保留字，未清洗时 `Nr. 10364`、`1914-07-06`、`K.u.k.`、`(Conrad, 1921, p. 284)` 之类查询会抛 `fts5: syntax error`，被 `except` 吞掉后**整条全文腿降级为空**（静默）。清洗后语义 = 拆成若干 bareword 做 AND 子串匹配。
  2. **必须 `ORDER BY rank`**——FTS5 不带 ORDER BY 时返回 rowid 序（=摄入顺序），而同一本书的 chunk 在 rowid 上连续，会导致全文腿 top-N **全部来自同一本书**且系统性偏向早期摄入的卷册（新灌入的 ÖUA/MRP/Conrad 几乎进不了候选集）。

---

## 四、语料库现状（详细统计）

### 4.1 规模

| 项目 | 数值 |
|---|---|
| chunk 总数 | **160,475** |
| 覆盖的 distinct title | **190** |
| bookdata 书目条目 | 192（其中 2 条因原文无文字层而无 chunk） |
| 向量维度 | 1024 |
| `db/` 占用 | **3.04 GB**（`chroma.sqlite3` 2.37 GB + HNSW 索引目录 679 MB） |

### 4.2 各维度分布

**source_type**

| 取值 | chunks | 占比 |
|---|---|---|
| secondary | 121,436 | 75.7% |
| **primary** | **34,733** | **21.6%** |
| mixed | 4,306 | 2.7% |

**language**

| 取值 | chunks | 占比 |
|---|---|---|
| 英文 | 116,134 | 72.4% |
| **德文** | **41,688** | **26.0%** |
| 混合 | 1,545 | 1.0% |
| 波兰文 | 1,108 | 0.7% |

**stance**

| 取值 | chunks | 占比 |
|---|---|---|
| 不涉及该争论 | 87,246 | 54.4% |
| 中立描述 | 37,289 | 23.2% |
| 衰落论 | 18,654 | 11.6% |
| 修正主义 | 17,286 | 10.8% |

**subfield**（多值，共 450,383 个标注）

政治史 23.6% · 社会史 15.9% · 民族史 14.3% · 外交史 11.8% · 军事史 11.4% · 地区研究 8.5% · 经济史 7.4% · 犹太史 7.0%

**region**（多值，共 591,222 个标注，30 个取值，前 12 位）

全帝国 17.5% · 巴尔干地区 9.3% · 意大利 7.7% · 俄罗斯帝国 7.1% · 德意志地区 6.4% · 加利西亚 5.5% · 下奥地利 4.8% · 波斯尼亚-黑塞哥维那 4.6% · 匈牙利本土 4.4% · 奥斯曼帝国 3.9% · 波希米亚 3.6% · 特兰西瓦尼亚 2.7%

**period**：全部 160,475 条均含该字段，覆盖年份区间 1180–2005。

### 4.3 chunk 的结构

**id 格式**：`{title}::{chunk_index}` —— 例如 `The Habsburg Empire: A New History::412`

**document（正文）**：纯文本。档案类 chunk 的正文首部带一个方括号前缀：

```
[ÖUA VIII · Nr. 10364 · 1914-07-06]
Nr. 10364 . Tel. nach Berlin Nr. 415. …
```

**metadata 字段**

| 字段 | 类型 | 覆盖率 | 说明 |
|---|---|---|---|
| `title` | str | 100% | 关联键 |
| `language` | str | 100% | |
| `chunk_index` | int | 100% | 该书内的序号，从 0 起 |
| `page_num` | int | **85.3% 有效** | 其余为 `-1`（EPUB/DOCX 来源无页码） |
| `chapter_title` | str | **17.1% 非空** | 仅 chapter 级书目且页码落在章节区间内 |
| `stance` / `source_type` | str | 100% | |
| `subfield` / `region` | list[str] | 100% | 数组字段，非空 |
| `period` | str | 100% | |
| `doc_number` | str | **13.1%** | 档案文件编号（如 `10364`） |
| `doc_date` | str | **13.0%** | ISO 格式（如 `1914-07-06`） |
| `doc_section` | str | 0.1% | 附件标记（如 `Beilage`） |
| `doc_part` | int | 档案类 | 该文件被切分后的第几块 |

### 4.4 chunk 词数分布（6 万抽样）

最小 66 · p25 183 · **中位 204** · p75 261 · p90 352 · 最大 673

### 4.5 单本规模

最大 3,424 chunks（*The First World War and the End of the Habsburg Monarchy, 1914-1918*），最小 3 chunks（一篇书评）。

前 8 位：3,424 · 2,918 · 2,842 · 2,727 · 2,724 · 2,576 · 2,562 · 2,552
后 5 位：41 · 34 · 33 · 20 · 3

### 4.6 语料的来源批次

| 批次 | 书目条数 | chunks | 切分方式 |
|---|---|---|---|
| 原有批次 | 136 | 126,263 | 按词数切分（`ingest.py`） |
| **ÖUA**（奥匈外交档案 1908–1914，8 卷） | 8 | 11,845 | 文档级切分（`ingest_new.py`） |
| **MRP**（奥地利/内莱塔尼亚部长会议记录 1848–1918，33 卷） | 33 | 9,109 | 文档级切分（TEI protocol 为界） |
| **Conrad**《Aus meiner Dienstzeit》Bd. I–V | 5 | 3,780 | 按词数切分（来源：上奥地利州立图书馆 API） |
| 新增专著/回忆录 | 10 | 9,478 | 按词数切分 |
| **合计** | **192** | **160,475** | |

---

## 五、检索链路（`corpus_lib.py`）

**入口**：`search_chunks(query, source_type, region, lang, subfield, stance, title, n_results, excluded, use_hybrid, use_rerank, use_rewrite, debug_log)`

`app.py` 与 `eval/run_eval.py` 共用此函数，保证评测与线上同源。

**完整流程**

```
① A9 查询改写（rewrite_queries）
   仅当查询含中日韩字符时触发。调用 DeepSeek 把问题改写为多条查询，
   提示词要求「至少1条英文 + 至少1条德文」（因库内德文一手档案占比高）。
   原查询 + 改写结果，最多 4 条。

② 对每条查询，并行跑两腿：
   向量腿：embed_text（bge-m3）→ collection.query(where=..., n_results*3)
   全文腿：fulltext_query → FTS5 语法清洗 → 直查 sqlite FTS5（trigram，ORDER BY rank）
           → 经 rowid→embedding_id→chunk_id 映射
   两腿结果用 _rrf_merge 融合（RRF 常数 k=60）

③ 跨查询再融合：对 ①-② 得到的多条列表再做一次 _rrf_merge

④ A8 精排（rerank_documents）
   取融合后前 max(30, n_results*3) 条，用 bge-reranker-v2-m3 打分。
   对 ①中每一条查询分别精排，取每篇的最高分（因精排分数对查询语言敏感）。
   失败自动降级为 RRF 顺序。

⑤ 过滤 excluded（会话级软排除）→ enrich_chunk 富化 → 截断至 n_results
```

**`build_where`** 支持的过滤维度：`source_type`（$eq）、`region`（$contains，支持列表→$or）、`subfield`（$contains，同上）、`lang`（$eq）、`stance`（$eq）、`title`（$eq）。全文腿在 Python 侧用 `_meta_matches` 复刻同一套语义。

**富化（`enrich_chunk`）**：把 chunk metadata 与 bookdata.json 的书目信息合并，输出展示用字典，含 `citation` 字段。档案类 chunk 的关键字段是 `doc_number` / `doc_date`。

**展示文本修正**：`get_corrected_text` / `correct_units` 用轻量模型（GLM 或 DeepSeek-flash）修正 OCR 噪声，结果按 chunk_id 列表缓存于 `textfix_cache.json`。**仅影响展示，检索与引用仍用原文。**

---

## 六、应用层（`app.py`）

### 6.1 三种问答模式

**① 普通模式（默认）** —— 单次检索 + 生成

```
detect_scope_title(问题)          程序化识别是否锁定单本书
  → search_chunks(n_results=15)   检索
  → 拼 context + 最近 6 轮历史
  → call_deepseek_stream          流式生成
  → postprocess_answer            引用校验
```

「继续对话（不重新检索）」按钮复用上一轮的完整候选池（`last_sources`）。

**② 深度分析模式** —— agent 自主工具循环

```
_make_retrieval_plan(问题)    A10：先让模型产出 1-4 条检索计划
   → 程序化执行计划，结果以 plan_N 的 tool 消息进入上下文
   → agent_loop                模型自主决定后续工具调用，上限 MAX_TOOL_CALLS=50
```

**③ 长文本分析模式** —— 三阶段台账式核查

```
阶段一 decompose_long_text   长文本 → 可核查论点清单
阶段二 verify_claim × N      每个论点独立小循环：可用全部工具 + record_verdict 提交裁决
                             裁决含 verdict(4值) / evidence_grade(4级) / citations /
                             chunk_ids / reasoning；每论点 20 次工具护栏，总体无上限
阶段三 build_report_messages → 流式综合报告
```

### 6.2 六个工具

| 工具 | 逻辑 |
|---|---|
| `search_corpus` | 封装 `search_chunks`；支持 source_type/region/lang/subfield/stance/title/n_results |
| `expand_chunk` | 按 `chunk_index ± window` 取同一 `title` 下的相邻片段 |
| `get_book_info` | 按 title 或 author 反查 bookdata；title 支持子串兜底匹配 |
| `list_sources_on_topic` | 语义检索后按书名去重，只返回书目列表不含正文 |
| `list_books_by_filter` | 纯结构化过滤（不做语义检索），返回符合 region/subfield/stance/source_type 的书目 |
| `exclude_chunks` | 把 chunk_id 加入会话级排除集合，后续检索与 expand 不再返回；**不占 n_results 名额** |

### 6.3 硬约束（不依赖模型自觉）

- **`detect_scope_title`**：从《书名》/引号内容与作者姓氏两个信号识别问题是否限定单本书；**只有唯一确定时才锁定**，有歧义则返回 None
- **`execute_tool(scope_title=...)`**：锁定时强制覆盖模型传的 title；`expand_chunk` 越界直接拒绝
- **`ui_filters()`**：侧边栏过滤条件在深度模式**硬覆盖**模型参数；长文本模式不使用侧边栏过滤
- 展示层对 scope_title 再做一次兜底过滤

### 6.4 后处理

**`postprocess_answer`** —— 一次 LLM 调用产出三样东西：

- `used_indices`：回答真正用到的片段 → 用于收敛展示面板
- `citation_issues`：疑似编造的引用（**认两类格式**：`(作者, 年份, p. 页码)` 与 `卷次, Nr. 编号`）
- `citation_map`：引用 ↔ 片段的对照表

**`merge_adjacent_chunks`** —— 展示前合并：同一 `title` 内 `chunk_index` 相差 ≤1 **且 `doc_number` 相同**的片段合并为一个展示单元（页码显示为区间）。`doc_number` 判断是为避免把两份不同的档案文件拼进同一个面板。

### 6.5 其余组件

- **开发者模式**：`dev_record` / `render_dev_log` 记录每一步的模型输入输出与工具调用（`DEV_LOG_MAX_ENTRIES=300`）
- **会话持久化**：`sessions/index.json` + 每会话一个 `.jsonl`；`sources` 只存 chunk_id，渲染时用 `hydrate_sources` 按 id 从库还原正文
- **导出**：`build_export_md` 组装「问题 + 回答 + 引用片段」
- **反馈**：`_append_feedback` 写 `feedback.jsonl`（当前文件不存在）
- **Light 模式**：`streamlit run app.py -- -light`，主任务模型与轻量任务模型切换

### 6.6 关键常量

`MAX_TOOL_CALLS = 50` · `MAX_HISTORY_TURNS = 6` · `LONG_CLAIM_MAX_TOOLS = 20` · `DEV_LOG_MAX_ENTRIES = 300`

---

## 七、入库链路

### 7.1 `ingest.py`（原有 136 本）

**分块参数**：`MIN_BLOCK_WORDS=5`（丢弃过短块）· `MERGE_THRESHOLD=100`（短块向后合并）· `MERGE_CAP=600` · `DIRECT_MAX=500` · `SUBCHUNK_MAX=500` · `OVERLAP_WORDS=75`（块间重叠）· `NOISE_REPEAT_THRESHOLD=3` + `NOISE_MAX_WORDS=20`（同书内逐字重复 ≥3 次的短块判为页眉页脚丢弃）

**流程**：`extract_blocks`（PDF 用 PyMuPDF `get_text("blocks")` 并做 `fix_hyphenation` / DOCX / EPUB 用 ebooklib）→ `filter_short_blocks` → `filter_noise_blocks` → `build_chunks` → `add_overlap` → `get_fields_for_chunk` 分配标签 → bge-m3 分批 embedding（16 条/批）→ 写 ChromaDB。失败时 `_cleanup_partial` 删除该书已写入部分，按 title 记录 `ingest_processed.txt` 断点续跑。

### 7.2 `ingest_new.py`（新增批次）

按 `classify(title)` 分四路，各用不同提取器：

| 提取器 | 适用 | 逻辑 |
|---|---|---|
| `extract_oua` | ÖUA 8 卷 | **文档级切分**：以"页内块首的 `Nr. NNNN` 标记"为唯一起始依据（仅首次出现算起始）；页眉用于提取日期；附件（`Beilage zu n. X`）独立成块并继承父号。文档内按 800 词上限切分并保留 75 词重叠，**文档间硬边界**。每块前置 `[卷次 · Nr. 编号 · 日期]`。断词修复用保守规则（仅当连字符后接小写字母才合并） |
| `extract_mrp` | MRP 33 卷 | 解析 TEI，取 `div type="protocol"` 为文档单元；**词数 <20 的视为空壳跳过**（1927 年司法宫大火烧毁的卷次只剩元数据）。每块前置 `[MRP 系列/部/卷 · Nr. 编号 · 日期]` |
| `extract_conrad` | Conrad 5 卷 | 逐页抓取上奥地利州立图书馆 Goobi IIIF API，按页累积至 500 词成块；软连字符 `¬` 直接删除 |
| `extract_pdf` / `extract_epub` | 新增专著 | 沿用 `ingest.py` 的词数切分规则（`BOOK_CAP=500`、`BOOK_MERGE=100`、`BOOK_OVERLAP=75`） |

**参数**：`DOC_CAP=800` · `DOC_OVERLAP=75` · `MIN_DOC_WORDS=20`

---

## 八、辅助组件

### 8.1 `db_check.py`

对比 `bookdata.json` / `metadata.json` / ChromaDB 三方，报告六类情形：有书目但零 chunk 的书、库内孤儿 title、bookdata 内部重复 title、两文件互相缺失、chunk 数异常低（<20）的书。发现问题时退出码为 1。

### 8.2 `pages/`

- **语料浏览**：按书目（按 chunk 数排序）→ 章节 → 全文过滤，分页展示原始片段及其全部标签；提供逐片段"修正排版"按钮
- **文献库管理**：概览指标 + 三方一致性检查 + **单书重新入库 / 删除该书全部 chunk**（会真实修改 ChromaDB）

### 8.3 `eval/`

**题库**：`questions.json`，12 题（q01–q12），字段为 `id / question / expected_titles / expected_citations / filters / gold_points / note`。

**指标**

- retrieval 模式：`title_hit_rate`（期望书目是否进入 top-k）、`mrr`、`citation_hit_rate`
- full 模式（额外）：`citation_support_rate`（把回答中的引用逐条回候选池核验，分 `page_supported` / `author_year_supported` / `author_year_only` / `unsupported`）、`mean_judge_score`（DeepSeek 对照 gold_points 打 1–5 分）

`--baseline` 可关闭 A7/A8/A9 增强以测旧基线。

---

## 九、引用规范（两类格式）

系统对两类史料使用两套引用格式，由 `corpus_lib.format_citation_tag` 统一生成（`app.py` 不再保留副本）。

| 史料类型 | 判定依据 | 输出格式 | 示例 |
|---|---|---|---|
| 二手著作与回忆录 | 无 `doc_number` | `(作者, 年份, p. 页码)`；无页码时省去 `p.` | `(Judson, 2016, p. 45)` |
| **档案汇编类** | 有 `doc_number` 且正文首部带 `[...]` 前缀 | `卷次, Nr. 编号`；附件追加 `(Beilage)` | `ÖUA VIII, Nr. 10364` · `MRP 3/8/2, Nr. 220` · `ÖUA I, Nr. 10361 (Beilage)` |

该格式同时用于：喂给模型的上下文标签、界面展开面板的标题、引用对照表、以及引用校验的核对口径。三处提示词（`SYSTEM_PROMPT` / `REPORT_SYSTEM_PROMPT` / 引用校验提示词）均已写明两类格式。

---

## 十、本文无法枚举的数据的位置

| 内容 | 位置 |
|---|---|
| **全部 192 条书目**（title/author/year/publisher/description 等 16 字段） | `bookdata.json` |
| **全部 192 条内容标签**（stance/subfield/period/region/source_type，含 chapter 级） | `metadata.json` |
| **全部 190 个在库书名及其 chunk 数** | ChromaDB；或运行 `python db_check.py` |
| **全部 160,475 个 chunk 的正文与元数据** | ChromaDB（`db/chroma.sqlite3`） |
| 每个 title 的 chunk 数与零 chunk 书目 | `python db_check.py` 的文本报告 |
| 各书的入库日志（含 chunk 数、失败原因） | `ingest_log.txt` / `ingest_new_log.txt` |
| 断点续跑状态（已完成 title 清单） | `ingest_processed.txt` / `ingest_new_processed.txt` |
| 原始文献文件 | `D:\哈布斯堡史`（143 PDF + 14 EPUB），文件名与 `bookdata.json` 的 `filename` 字段对应 |
| MRP 的 TEI 源文件 | `C:\Users\notch\Desktop\oeaw-ministerratsprotokolle-mp-edition-data-4f261cb\` |
| 建书目阶段的脚本与中间产物 | `bookdata/`（含 `README.md` 详述该阶段流程） |
| 对话存档 | `sessions/index.json` + `sessions/*.jsonl` |
| 展示层排版修正缓存 | `textfix_cache.json` |
| 评测题库与历史结果 | `eval/questions.json`、`eval/results_*.json` |

---

## 十一、外部依赖

| 用途 | 服务 | 模型 |
|---|---|---|
| 主任务生成 | DeepSeek | `config.DEEPSEEK_MODEL` |
| 轻量任务（查询改写、排版修正、引用核对） | DeepSeek / 智谱 GLM | `config.DEEPSEEK_MODEL_LIGHT` / `config.GLM_MODEL` |
| 向量化 | SiliconFlow | `BAAI/bge-m3`（1024 维） |
| 精排 | SiliconFlow | `BAAI/bge-reranker-v2-m3` |

全部配置集中在 `config.py`，另含四个检索增强开关：`HYBRID_SEARCH_ENABLED`（A7 向量+全文 RRF）、`RERANK_ENABLED`（A8 精排）、`QUERY_REWRITE_ENABLED`（A9 查询改写）、`RERANK_CANDIDATES`。
