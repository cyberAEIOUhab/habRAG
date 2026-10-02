# habRAG 操作指南

**用途**：扩容（3 GB → 几十 GB）、架构改造（全文腿）、迁移选型。
**基线日期**：2026-09-17 注入完成后。
**配套文档**：`docs/ARCHITECTURE.md`（项目全貌，给任何 LLM 看的那份）。

---

## 0. 当前状态基线

### 0.1 数据

| 项 | 值 |
|---|---|
| chunk 总数 | **160,475** |
| 书目 | 190 种 |
| `db/` 磁盘占用 | **3.04 GiB**（sqlite 2.37 + HNSW 0.66） |
| 每块成本 | **20,325 B ≈ 19.85 KiB** |
| 向量 | 160,475 × 1024 维 float32 |
| 正文 | 269.9 MiB，平均 1,764 B/块（约 204 词） |

### 0.2 `db/` 构成（实测，非推算）

| 组件 | MiB | 占比 | 字节/块 |
|---|---:|---:|---:|
| 元数据表 + 9 个二级索引 + `embeddings` 表 | 1,382.9 | **44.5%** | 9,037 |
| FTS5 · trigram 全文索引 | 777.7 | 25.0% | 5,082 |
| HNSW · 向量 + 图 | 679.5 | 21.8% | 4,442 |
| FTS5 · 正文本体 | 269.9 | 8.7% | 1,764 |
| **合计** | **3,110.0** | 100% | **20,325** |

> 三个关键事实，都经实测确认：
> 1. **最大单项是元数据**，不是全文索引。Chroma 给 `embedding_metadata` 和 `embedding_metadata_array` 无条件建了 8 个二级索引。
> 2. **trigram 索引 = 3.07 × 正文**（不是 6.9×，那是把元数据 B 树开销算进去的错误归因）。
> 3. **各组件均随规模线性增长**。trigram 每行开销在 16 万 / 32 万 / 64 万行时分别为 5,417 / 5,386 / 5,383 B，无超线性膨胀。

### 0.3 注入速率（从 `ingest_new_log.txt` 实测）

| 来源类型 | 速率 | 说明 |
|---|---:|---|
| 专著（PDF/EPUB） | **0.066 s/块** | 8,977 块 / 594 s |
| ÖUA（PDF 书签分卷） | **0.073 s/块** | 11,845 块 / 864 s |
| MRP（TEI XML） | **0.122 s/块** | 8,674 块 / 1,057 s |
| **Conrad（OOeLB ALTO 逐页抓取）** | **1.225 s/块** | 3,780 块 / 4,631 s，慢 12–18× |

**扩容时间估算**：文稿类来源按 0.08 s/块；若含扫描页 API 来源，按 1.2 s/块单独计。

### 0.4 磁盘现实（约束测试规模）

| 盘 | 可用 |
|---|---:|
| C: | 21.4 GB |
| D: | 30.7 GB |

**30 GiB 的完整压测装不下。** 用下文的 4× 方案。

---

## 1. 日常运维

### 1.1 启动与重启

```powershell
cd C:\Users\notch\Desktop\habRAG
streamlit run app.py
```

> **改过 `app.py` 或 `corpus_lib.py` 后必须整个重启 Streamlit。**
> 界面上的 "Rerun" 不会重新 import 模块，改动不生效。

### 1.2 备份

**先停掉 Streamlit**（Chroma 的 sqlite 是单写入者，运行中复制会得到损坏的库）。

```powershell
# 停掉 Streamlit 后执行
robocopy C:\Users\notch\Desktop\habRAG\db  D:\habRAG_backup\db  /MIR /R:1 /W:1
robocopy C:\Users\notch\Desktop\habRAG\*.json D:\habRAG_backup\json *.json /R:1 /W:1
```

必带的三类资产（丢了不可再生）：
1. `db/` —— 160,475 块的向量与索引
2. `textfix_cache.json` —— 你手工做过的排版修正
3. `bookdata.json` / `metadata.json` / `book.json` —— 书目与标签

> **不要 `VACUUM`**。实测空闲页只有 2,367 页（9.2 MiB），库是 99.6% 装满的，榨不出空间，只会白白需要 2× 临时空间。

### 1.3 体检

```powershell
cd C:\Users\notch\Desktop\habRAG
python db_check.py
```

正常输出：chunk 总数 160,475，无零块书目。
**已知的两个历史遗留零块条目**（不是故障）：`Exclusive Revolutionaries`、`History and Myth in Romanian Consciousness`。

快速查块数：

```python
import sqlite3
con = sqlite3.connect("file:C:/Users/notch/Desktop/habRAG/db/chroma.sqlite3?mode=ro",
                      uri=True, timeout=30)
print(con.execute("SELECT count(*) FROM embeddings").fetchone()[0])
```

### 1.4 排错速查

| 症状 | 原因 | 处置 |
|---|---|---|
| 检索结果明显只有语义相近的内容，精确术语查不到 | 全文腿失效 | 开发者模式看 `_FULLTEXT_OK` / `_FULLTEXT_ERR` |
| `attempt to write a readonly database` | Chroma 需要以**读写**模式打开 sqlite，即使只查询 | 确认 `db/` 目录可写；不要把库放只读挂载 |
| 德文姓名拼写变体召回暴跌 | FTS5 trigram **不做变音符折叠**：`Hötzendorf` 401 条 vs `Hoetzendorf` 16 条 | 查询侧同时跑两种拼法，或引入变音符折叠 |
| 日期查询返回大量无关片段 | `1914-07-06` 清洗后变成 `1914 AND 07 AND 06` 子串共现，命中 1.6 万条 | 日期查询走 `doc_date` 元数据过滤，别走全文腿 |
| 改了代码但行为没变 | Streamlit 未重启 | 见 1.1 |

**全文腿的实现要点（改动前必读，`corpus_lib.fulltext_query`）**

1. 查询串必须先清洗：`re.sub(r"[^\w]+", " ", q)`。
   FTS5 把 `. , - / ( ) * :` 当保留字，不清洗时 `Nr. 10364`、`1914-07-06`、`K.u.k.`、`(Conrad, 1921, p. 284)` 都会抛语法错误并被 `except` 吞掉，**整条腿静默失效**。
2. SQL 必须带 `ORDER BY rank`。不带时 FTS5 返回 **rowid 序（= 摄入顺序）**，而同一本书的 chunk 在 rowid 上连续，会导致全文腿 top-N 全部来自同一本书，并系统性埋没后灌入的档案卷。

---

## 2. 扩容前压测

### 2.1 测试 A：全文腿延迟曲线（已完成）

用真实语料建同构 FTS5 trigram 表，逐级放大，测 `fulltext_query` 的实际耗时。

「有ORDER」= 实际生产路径；「无ORDER」= 对照，仅看排序本身的代价。

| 词 | 1× 匹配 | 1× | 2× | 4× | 6× | 6×/1× |
|---|---:|---:|---:|---:|---:|---:|
| Krieg | 18,118 | 45.0 ms | 93.0 ms | 213.9 ms | **313.5 ms** | 7.0× |
| Österreich | 15,729 | 98.3 ms | 225.3 ms | 388.2 ms | **581.7 ms** | 5.9× |
| Conrad | 6,511 | 18.3 ms | 42.5 ms | 89.9 ms | 113.8 ms | 6.2× |
| Ultimatum | 1,996 | 13.5 ms | 34.3 ms | 43.6 ms | 106.3 ms | 7.9× |
| Zwischenzollinie | 25 | 25.6 ms | 60.4 ms | 118.2 ms | 190.7 ms | 7.5× |

**结论**：`ORDER BY rank` 的代价 **≈ 线性于匹配行数 ≈ 线性于库大小**（1×→6× 全段实测 5.9–7.9×，贴合 6× 规模）。

**第二个发现**：`Zwischenzollinie` 匹配行数只从 25 涨到 100，延迟却从 25.6 ms 涨到 118.2 ms（4.6×）。
原因：FTS5 处理多字符查询要做 **trigram 倒排求交**，而常用 trigram（`sch`、`isc`…）的 posting list 会随语料增长。
**所以即使是罕见词查询，也会随库变大而变慢**——只是比高频词慢得多。

**外推到 10×（约 160 万块 / 30 GiB）**——以 6× 实测为锚，×1.67：

| 词型 | 单次全文腿耗时（实测外推） |
|---|---:|
| 高频词（Österreich 级） | **≈ 970 ms** |
| 高频词（Krieg 级） | ≈ 520 ms |
| 罕见词（Zwischenzollinie 级） | ≈ 320 ms |
| 中频词（Conrad 级） | ≈ 190 ms |
| 中低频词（Ultimatum 级） | ≈ 180 ms |

`search_chunks` 对**最多 4 条查询**各跑一次全文腿 → **单次检索的全文腿最坏约 2–4 秒**。

> 这是"全文腿在百万块规模会不会成为瓶颈"的直接答案：**会**。但它不是靠猜——上表就是可复现的基线，4× / 6× 的数字可以用下面同一段脚本补测。

### 2.2 测试 B：端到端 4× 压测

**目的**：验证 Chroma 在 4× 规模下的启动内存、端到端延迟，并线性外推到 10×。
**成本**：约 25–35 分钟，¥0（**向量直接复制，不重新调 embedding**）。
**空间**：4 × 3.04 GiB ≈ **12.2 GiB**，建议放 D:（30.7 GB 可用）。
**已验证**：本脚本的复制逻辑已实测（数组元数据 `region`/`subfield` 完整保留，写入速率 **476 块/秒**）。

```python
# pressure_test.py —— 把现有 collection 复制 COPIES 份，测端到端指标
# 用法：python pressure_test.py            （默认 3 份 → 库里变 4×）
import os, sys, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chromadb, corpus_lib as C

DST    = r"D:\habRAG_scale_test"   # 临时库（D 盘空间更大）
COPIES = 3                          # 复制份数，最终规模 = (COPIES+1) ×
BATCH  = 2000

if not os.path.exists(DST):
    os.makedirs(DST, exist_ok=True)
    src  = C.get_collection()
    cli  = chromadb.PersistentClient(path=DST)
    dst  = cli.get_or_create_collection(name="habsburg", metadata={"hnsw:space": "l2"})
    n    = src.count()
    print(f"源库 {n} 块 → 目标 {n * (COPIES + 1)} 块")
    t0, off = time.time(), 0
    while off < n:
        r = src.get(limit=BATCH, offset=off,
                    include=["embeddings", "documents", "metadatas"])
        for k in range(COPIES + 1):
            dst.add(ids=[i + f"__c{k}" for i in r["ids"]],
                    embeddings=r["embeddings"],
                    documents=r["documents"],
                    metadatas=r["metadatas"])
        off += len(r["ids"])
        print(f"  {off}/{n}  {time.time() - t0:.0f}s", flush=True)
    print(f"写入完成，共 {dst.count()} 块，耗时 {time.time() - t0:.0f}s")
else:
    print("临时库已存在，直接复用：", DST)

# ---------- 指标 1：全文腿延迟（直查压测库的 FTS5）----------
import sqlite3
print("\n全文腿延迟:")
con = sqlite3.connect(f"file:{DST}/chroma.sqlite3?mode=ro", uri=True, timeout=30)
for w in ["Krieg", "Österreich", "Conrad", "Ultimatum", "Zwischenzollinie"]:
    n = con.execute("SELECT count(*) FROM embedding_fulltext_search "
                    "WHERE embedding_fulltext_search MATCH ?", (w,)).fetchone()[0]
    reps = []
    for _ in range(3):
        t = time.perf_counter()
        con.execute("SELECT rowid FROM embedding_fulltext_search "
                    "WHERE embedding_fulltext_search MATCH ? ORDER BY rank LIMIT 300", (w,)).fetchall()
        reps.append((time.perf_counter() - t) * 1000)
    print(f"  {w:<18} 匹配 {n:>8}   ORDER BY rank {min(reps):>8.1f} ms")
con.close()

# ---------- 指标 2：端到端检索 ----------
# 关键：corpus_lib 用的是模块级 CHROMA_DB_PATH，不覆盖就会去测真实库！
C._collection    = None          # 清掉单例，强制用新路径重开
C.CHROMA_DB_PATH = DST
C._FTS_URI       = "file:" + DST.replace("\\", "/") + "/chroma.sqlite3?mode=ro"
print("\n端到端 search_chunks（关闭 rerank / rewrite，只测两腿+RRF）:")
for q in ["Zwischenzollinie", "Serbien 1914", "ÖUA VIII, Nr. 10364"]:
    t = time.perf_counter()
    r = C.search_chunks(query=q, n_results=10, use_rerank=False, use_rewrite=False)
    print(f"  {q:<22} {len(r)} 条   {(time.perf_counter() - t) * 1000:.0f} ms")

# ---------- 指标 3：常驻内存 ----------
try:
    import psutil
    print("\n常驻内存 RSS = %.2f GB" % (psutil.Process(os.getpid()).memory_info().rss / 1073741824))
except ImportError:
    print("\n（pip install psutil 后可测 RSS）")
```

> **RSS 要这样读才准**：必须在**跑完检索之后**读，并且**第二次运行脚本**（此时 `DST` 已存在会跳过复制）——那才是一个干净进程"打开压测库 + 检索"的真实内存占用。第一次运行的 RSS 混入了复制过程的残留。

**外推方法**：把 4× 的实测值除以 4 得到"每倍成本"，再乘 10 即得 10× 的预期。
若 4× 的实测与 1× 的比值明显大于 4，说明存在非线性，需重新评估架构。

### 2.3 判定阈值（go / no-go）

> **先说明**：第 2.1 节已经把**全文腿**这一项测到 6× 了，那一栏的答案已知（10× 外推约 0.2–1.0 s/次，属红线区）。
> 所以测试 B 的**增量价值只剩两项**：**常驻内存**和**端到端总延迟**——这两项纯 sqlite 测不出来，必须走 Chroma。

| 指标 | 4× 实测若 ≤ | 10× 外推 | 判定 |
|---|---|---:|---|
| 常驻内存 RSS | 6 GB | ≤ 15 GB | 单机可行（16 GB 起步，32 GB 舒适） |
| 端到端 `search_chunks`（无 rerank） | 1 s | ≤ 2.5 s | 可接受 |
| 端到端 `search_chunks`（无 rerank） | > 2 s | > 5 s | **必须改造全文腿**（见第 3 节），因为全文腿是其中可优化的一块 |

若只想快速得到结论、不想跑测试 B：**全文腿这一项已经可以直接判红了**（见 2.1 的 10× 外推表），内存则可按 4,442 B/块 × 目标块数直接估算，无需实测。

---

## 3. 架构改造：trigram → BM25 稀疏向量

### 3.1 为什么（收益可量化）

| | 现状（FTS5 trigram） | 换成 BM25 稀疏向量 |
|---|---:|---:|
| 每块索引开销 | **5,082 B** | **≈ 900 B** |
| 排序检索延迟 | ∝ 匹配行数（1× 已达 45–98 ms，10× 约 0.5–1 s） | 倒排索引带 WAND / block-max 剪枝，**不随匹配行数线性恶化** |
| 存储（30 GiB 库） | trigram 约 7.6 GiB | 约 1.4 GiB |

配合移除冗余元数据索引（9,037 B/块 → 约 300 B/块），**每块从 19.85 KiB 降到约 7 KiB，30 GiB 的库缩到约 11 GiB。**

### 3.2 何时做

- **不建议现在做。** 160k 规模下全文腿是健康且刚修好的。
- **触发条件**：压测显示全文腿已成瓶颈（第 2.3 节红线），**或**决定迁移到 Zilliz / Milvus（它们的词法腿本来就是 BM25 稀疏向量，见第 4 节）。
- 换句话说：**改造和迁移是同一步**。若走自建路线，改造后仍需自己维护索引；若走托管路线，迁移时顺便就换了。

### 3.3 验收标准（必须过的回归）

改造前后用同一套基准比对 **recall@30**。当前全文腿的基线（12 个领域术语，实测）：

```
Zwischenzollinie  25 条  100%      Probemobilisierung  28 条  100%
Szogyeny         292 条  100%      Bogicevic          257 条  100%
Czernin        1,353 条  100%      Hötzendorf         401 条  100%
Annexionskrise   140 条  100%      Teilungsvertrag      6 条  100%
Zwischenfall     162 条  100%      Kriegsministerium 1,068 条 100%
Ausgleich      1,621 条  100%      Ultimatum         1,989 条  100%
────────────────────────────────────────────────────────────────
全文腿 recall@30 = 100.0%    向量腿 recall@30 = 47.4%
```

**任何改造后，这 12 个术语的 recall@30 不得低于 95%。** 低于此说明词元语义替代不了子串语义，需要补一条子串兜底腿。

### 3.4 语义变化（必须知情）

| 查询形态 | trigram（现在） | BM25（改造后） |
|---|---|---|
| `Zwischenzollinie` | 精确子串 | 基本等价 |
| `Nr. 10364` | 精确子串 | 词元 `nr` + `10364`，语义相近 |
| 跨词边界、词中片段 | 支持 | **不支持** |
| 拼写变体 `Hoetzendorf` | 不支持（16 条） | 仍不支持，需另做变音符折叠 |
| 相关度排序质量 | 弱（trigram 无 IDF） | **强（有 IDF）** |

---

## 4. 迁移选型

### 4.1 触发条件

满足任一条才考虑迁移；否则留在本地（改代码有成本，且现架构在 160k 规模是健康的）：

1. 压测显示全文腿或内存成为瓶颈，且不想做第 3 节的改造
2. `db/` 超过单机磁盘/备份的可控范围
3. 需要多端访问、或机器不再常开

### 4.2 三个方案

| 方案 | 30 GiB 时月成本 | 代码改动 | 全文腿 | 中国可达 |
|---|---|---|---|---|
| **自建 ECS** | 需 16 GB RAM + 100 GB ESSD | **零** | 原样保留 | ✅ |
| **Zilliz Serverless** | 存储 ~¥12–18 + vCU → **¥20–50** | 约 10 处 + 重做 Schema | BM25 稀疏向量 | ✅ 阿里云杭州 |
| **Zilliz Dedicated** | 1 CU 容量型 **¥912**（1 年付 ¥638） | 同上 | 同上 | ✅ 杭州/上海/北京/深圳 |
| Chroma Cloud | **≈¥60** | 最小（同 API） | 需重写为 Search API | ❌ 仅美东/欧西部 |

**Zilliz 的关键约束**：Free 和 Serverless **只能在阿里云华东 1（杭州）**；Free 层仅 5 GB 存储，30 GiB 规模直接出局。官方对 Free 的描述是"基础的向量数据库功能"，**BM25 / hybrid_search 是否可用必须先实测**（见 4.3）。

**Zilliz 迁移的真实工作量**（已数过）：`corpus_lib.py` 4 个函数 + `app.py` 6 个调用点 ≈ **10 处**，外加**重做整个 Schema**（Chroma 无 schema，Milvus 要显式声明每个字段、类型、nullable、`max_length`、`ARRAY` 维度）。全文腿从"直查 sqlite"改为 `hybrid_search()` + BM25 稀疏向量（Milvus 的 `RRFRanker` 默认 **k=60**，与现有 `_RRF_K` 一致）。

### 4.3 迁移前的最小验证（¥0）

注册 Zilliz Free 集群（杭州，无需绑支付方式），做三件事：

1. 建带 `enable_analyzer` 的 VARCHAR 字段 + BM25 Function + 稀疏向量索引
2. 确认 **Free 层是否允许 `hybrid_search`**
3. 灌 1,000 行样本，跑第 3.3 节那 12 个术语的 recall@30，与 **100%** 基线比对

---

## 5. 已知坑清单

| # | 坑 | 影响 | 状态 |
|---|---|---|---|
| 1 | FTS5 保留字未清洗导致整条全文腿静默失效 | 13/20 常见查询形态失效 | **已修**（`fulltext_query` 查询串清洗） |
| 2 | 全文腿缺 `ORDER BY rank`，返回摄入顺序 | top-N 全部来自同一本书，新档案被埋没 | **已修** |
| 3 | trigram 不做变音符折叠 | `Hoetzendorf` 仅 16 条 vs `Hötzendorf` 401 条 | 未处理 |
| 4 | 清洗后日期变子串 AND，噪音大 | `1914-07-06` 命中 1.6 万条 | 未处理，建议改走 `doc_date` |
| 5 | `ORDER BY rank` 代价 ∝ 匹配行数 | 百万块规模全文腿 0.5–1 s/次 | 未处理，见第 3 节 |
| 6 | 元数据 9 个二级索引占 44.5% 空间 | 每块 9,037 B | 未处理 |
| 7 | Chroma 需读写模式打开 sqlite | 只读环境无法实例化 collection | 设计如此 |
| 8 | Streamlit 改代码必须重启 | 改动不生效 | 设计如此 |
| 9 | OOeLB ALTO 抓取慢 12–18× | Conrad 类来源入库极慢 | 设计如此，规划时间时要算进去 |

---

## 6. 推荐执行顺序

1. **现在**：重启 Streamlit，让 `corpus_lib.py` 的两个修复生效（第 1.1 节）
2. **扩容前**：跑一次测试 B 的 4× 压测，拿到内存与延迟的实测曲线（第 2.2 节，¥0，半小时）
3. **按 2.3 的阈值判定**：
   - 全绿 → 直接按几十 G 扩容，架构不动
   - 全文腿红线 → 进第 3 节，摘掉 trigram 换 BM25
4. **只有当 4.1 的触发条件成立时**，才进第 4 节做迁移；先用 4.3 的方式 ¥0 验证
