# bookdata 处理文档

## 目录结构

```
habRAG/
├── bookdata.json          # 最终书目元数据（程序读写目标）
├── config.py              # DeepSeek API 配置
├── .claude/               # Claude Code 内部文件
└── bookdata/              # 本文件夹：所有处理中间物与脚本
    ├── README.md           # 本文档
    ├── log.txt             # 逐本处理日志（断点续跑依据）
    ├── baseline_extract.json  # PDF/EPUB/DOCX 原始提取（首页文字+书签+页数）
    ├── batches/            # 批量处理的中间输入JSON
    └── scripts/            # 所有处理脚本
```

---

## 总体流程（142本书是怎么生成的）

整个任务分为四个阶段：

### 阶段一：目录扫描与初始化

扫描 `C:\Users\notch\Desktop\哈布斯堡史\` 下所有文件，得到142个文件（128 PDF + 13 EPUB + 1 DOCX）。

写入 `log.txt` 顶部的完整文件列表，初始化空的 `bookdata.json`（`[]`）。

### 阶段二：批量原始数据提取

脚本：`scripts/extract_baseline.py`

对每个文件，用 PyMuPDF（PDF）、ebooklib（EPUB）、python-docx（DOCX）提取：
- **PDF**：前3页文字、`get_toc()` 书签/大纲、总页数、是否扫描件（前3页<500字符→扫描件）
- **EPUB**：前几个文档的文字、TOC结构
- **DOCX**：前50段的文字

结果写入 `baseline_extract.json`（142条，含文件路径、页数、书签列表、首页文字预览等）。

命令：
```bash
cd C:\Users\notch\Desktop\habRAG\bookdata
python -X utf8 scripts/extract_baseline.py
```

### 阶段三：逐本网络搜索 + 三方交叉验证

这是核心步骤。每本书的数据来自三个来源的交叉验证：

| 来源 | 说明 | 信任优先级 |
|------|------|-----------|
| **A：文件名解析** | 从文件名尝试解析title/author/year | 最低 |
| **B：首页文字提取** | 从baseline_extract.json中获取的前几页文字 | **最高（最接近原始文献）** |
| **C：网络搜索** | WebSearch该书的书名+作者，搜索结果返回规范信息 | 中等 |

**交叉验证规则：**
- A/B/C 三方一致 → `extraction_confidence: "high"`, `needs_review: false`
- 存在分歧 → 以B（首页提取）为准，分歧写入 `extraction_notes`，`needs_review: true`
- B提取失败（扫描件/EPUB报错）→ 以C为准，`needs_review: true`，`extraction_confidence: "low"`

**网络搜索策略：**
- 优先信任来源：出版社官网 > 学术书评(H-Net, JSTOR) > Google Books > Wikipedia
- 搜索到明确信息 → 综合改写成150-250字中文简介 → `description_source: "web_search"`
- 未搜到但自身已知（经典著作）→ 基于知识写简介 → `description_source: "model_knowledge"`
- 两者都无 → `description: null`, `description_source: "not_found"`

**执行方式：**
1. 将142本书分成了约10批，每批10-15本
2. 每批先并行WebSearch（10个搜索同时发出）
3. 搜索结果返回后，逐本撰写完整metadata条目
4. 每写完一批（10本），立刻通过 `scripts/write_batch.py` 追加入 `bookdata.json`，同时更新 `log.txt`
5. `log.txt` 格式：`文件名 | DONE | 时间戳 | conf=X review=Y desc_src=Z`

### 阶段四：最终统计与质量评估

全142本完成后，运行统计脚本输出：
- `description_source` 分布（web_search/model_knowledge/not_found）
- `extraction_confidence` 分布（high/medium/low）
- `needs_review` 清单（共46本，含具体原因）
- 语言分布、年代分布、priority_tier分布

---

## 如何新增文献

当你向 `C:\Users\notch\Desktop\哈布斯堡史\` 添加了新文件后，按以下步骤操作：

### 步骤1：增量提取原始数据

新增文件后，需要重新运行 `extract_baseline.py`。该脚本支持断点续跑——已存在于 `baseline_extract.json` 中的文件会自动跳过。

```bash
cd C:\Users\notch\Desktop\habRAG\bookdata
python -X utf8 scripts/extract_baseline.py
```

### 步骤2：对每本新书逐个处理

对每一本新书：

**(a) 从 `baseline_extract.json` 中找到新书的首页文字和书签数据**

**(b) 做网络搜索：**
```
搜索词：书名 + 作者名
优先查看：出版社官网、H-Net书评、Google Books、Wikipedia
```

**(c) 从三个来源解析 title/author/year：**
- 来源A：文件名
- 来源B：baseline_extract.json 中的首页文字
- 来源C：网络搜索结果

**(d) 交叉验证，确定以下字段：**

| 字段 | 说明 |
|------|------|
| `filename` | 完整文件名（含扩展名） |
| `filepath` | 完整路径（从baseline_extract.json获取） |
| `title` | 单一稳定书名（用于ChromaDB $eq精确匹配，不能有多个版本） |
| `author` | 作者标准名 |
| `year` | 出版年份（整数） |
| `language` | 中文/英文/德文/匈牙利文/混合 |
| `publisher` | 出版社（找不到填 `null`） |
| `page_count` | 总页数 |
| `is_scanned` | 布尔值，是否为扫描版 |
| `has_bookmarks` | PDF：布尔值；非PDF：`null` |
| `bookmark_titles` | 书签标题数组（无则为`[]`） |
| `description` | 150-250字中文简介（论点+方法+学术定位） |
| `description_source` | `"web_search"` / `"model_knowledge"` / `"not_found"` |
| `extraction_confidence` | `"high"` / `"medium"` / `"low"` |
| `needs_review` | 布尔值，title/author/year有不确性则为`true` |
| `extraction_notes` | needs_review的具体原因（无问题则为空字符串） |
| `priority_tier` | `"standard"` / `"high"`一手史料整理、稀缺小语种文献等你觉得值得后续逐chunk精细处理的书目，由Claude Code根据书籍性质初步判断，比如识别到"文献集/档案汇编/书信集"这类type时可倾向标记为high，但最终由你人工确认） |

**(e) 书名——最重要的字段**

`title`字段最终用于ChromaDB的精确匹配（`$eq`查询），必须是**单一、稳定**的字符串：
- 以首页提取的书名为准（来源B）
- 同一本书在馆藏中有多个版本时（如扫描版+非扫描版），各版本各自著录
- 有多卷作品时，每卷各自著录，书名末尾标注卷次

**(f) 书签/章节检测**

PDF文件：从 `baseline_extract.json` 获取 `bookmark_titles`。
- 有书签：`has_bookmarks: true`, `bookmark_titles`填完整列表
- 无书签：`has_bookmarks: false`, `bookmark_titles: []`
- 非PDF：两个字段都填 `null`

### 步骤3：写入 bookdata.json

有两种方式：

**方式A：逐本写入（新增1-2本时推荐）**

直接对我说："参考md文件，为新书《XXX》补充bookdata.json"，我会：
1. 读取baseline_extract.json获取首页文字
2. 做网络搜索
3. 交叉验证并生成完整metadata
4. 追加入bookdata.json并更新log.txt

**方式B：批量写入（新增多本时推荐）**

1. 先准备好每条书目数据，写入一个JSON文件（格式参见 `batches/batch_XXX_entries.json` 中的任一条目）
2. 运行：
```bash
cd C:\Users\notch\Desktop\habRAG\bookdata
python -X utf8 scripts/write_batch.py <你的entries文件.json>
```

### 步骤4：验证

```bash
cd C:\Users\notch\Desktop\habRAG
python -X utf8 -c "
import json
with open('bookdata.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(f'Total books: {len(data)}')
# 检查最后一条是否为你新增的书
print(data[-1]['title'])
"
```

---

## 142本处理中的关键经验

### EPUB处理
ebooklib 对全部13个EPUB文件提取均失败（可能由于DRM或格式兼容性问题）。因此所有EPUB文件的metadata均依赖**文件名+网络搜索**验证，`extraction_confidence`普遍为`"medium"`，`needs_review`普遍为`true`。

解决方案：用Calibre打开EPUB查看元数据，人工核对后更新。

### 扫描版PDF
67本PDF为扫描版（前3页提取文字<500字符），无法从首页提取文字。这些书的metadata依赖**文件名+网络搜索**，建议人工核对版权页。

### 多卷作品
以下多卷集按各自卷次分别著录：
- Österreich-Ungarns letzter Krieg（4卷，德文原版）
- The Origins of the War of 1914（3卷，Albertini）
- The Multinational Empire（2卷，Kann）
- October Fifteenth（2卷，Macartney）
- 一战奥官/英译（2卷，Legacy Books Press英译本）

### 同名文件的不同版本
部分书有多个文件版本（如Pieter Judson的Exclusive Revolutionaries同时有17.8MB扫描完整版和3.8MB/11页非扫描版[疑为导论或摘要]），分别著录为独立条目，在`extraction_notes`中标注关系。

### 文件名≠实际内容
偶有文件名标注为某一章节而文件实际包含全书的情况（如 `Austria-Hungary's Economy in World War I.pdf` 实际为Broadberry & Harrison编《The Economics of World War I》全书）。遇到此类情况，以首页提取的书名为准，在`extraction_notes`中说明分歧。

### 中文文献
最后几本中文文献的作者信息高度不确定（多数无法通过web_search找到直接匹配）。这些条目的`description_source`为`"model_knowledge"`，`needs_review`标记为`true`，需要人工核对PDF首页/版权页。

---

## 后续扩展方向

bookdata.json 是**书籍层面的稳定元数据**，后续可在此基础上逐chunk添加：

- **historiography**：学派的史学流派标签（如Fischer thesis, Revisionist, Cliometrics等）
- **period**：覆盖的历史时期（如1648-1815, 1848-1918, 1914-1918等）
- **region**：涉及的地理区域（Cisleithania, Transleithania, Galicia, Bohemia等）
- **theme**：主题标签（nationalism, economic history, military history, Jewish studies等）
- **primary_source**：布尔值，是否为一手史料/档案文献
- **chapters**：章节级别元数据（从bookmark_titles扩展）
