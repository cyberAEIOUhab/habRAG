# eval/ —— habRAG 评估套件（本次新增）

用于量化回答质量的三个维度：**检索命中**、**引用准确**、**事实一致**。
完全独立于 `app.py`（通过 `corpus_lib.py` 读取同一套语料库），不会修改任何现有文件。

## 文件

| 文件 | 说明 |
|---|---|
| `questions.json` | 种子问题集（12 题），每题含期望书目、期望引用、可选过滤条件、参考答案要点 |
| `run_eval.py` | 评测脚本（retrieval / full 两种模式） |
| `results_*.json` | 每次运行的结果（自动生成） |

## 用法（在项目根目录执行）

```bash
# 只评测检索：走与 app.py 完全同源的增强管线（A9改写+A7混合+A8精排）
# 含中文的题会各多一次小额度 DeepSeek 改写调用
python -X utf8 eval/run_eval.py

# 旧基线（完全免费）：关闭增强，纯向量检索，用于前后对比
python -X utf8 eval/run_eval.py --baseline

# 前 5 题，top-k 放宽到 20
python -X utf8 eval/run_eval.py --limit 5 --k 20

# 完整模式：检索 + 生成回答 + 引用支撑检查 + 裁判打分
# ⚠️ 每题约 2-3 次 DeepSeek 调用（生成 1 次 + 裁判 1 次），默认建议限制题数
python -X utf8 eval/run_eval.py --mode full --limit 3
```

## 指标说明

### retrieval 模式（默认）
- **期望书目命中率（title_hit_rate）**：`expected_titles` 中的书有多少进入了 top-k。
- **MRR**：第一本期望书目最早出现位置的倒数排名的平均（越接近 1 越好）。
- **期望引用命中率（citation_hit_rate）**：`expected_citations` 中的 `(作者姓氏, 年份)`
  是否出现在返回片段的 citation 字段中。

### full 模式（额外）
- **引用支撑率（citation_support_rate）**：把回答里所有 `(作者, 年份, p.X)` 标注提取出来，
  逐一检查能否在本次检索候选池的 citation 中找到依据：
  - `page_supported`：作者、年份、页码都能对上
  - `author_year_supported` / `author_year_only`：作者年份能对上（无页码/页码对不上）
  - `unsupported`：候选池里完全没有 → 疑似编造引用
- **裁判平均分（mean_judge_score）**：用 DeepSeek 对照 `gold_points` 打分（1-5），
  并列出回答覆盖了哪些要点、与要点矛盾或疑似编造的内容。

## 问题集格式（往 questions.json 里加题）

```json
{
  "id": "q13",
  "question": "问题文本（中文）",
  "expected_titles": ["库内精确书名"],
  "expected_citations": ["作者姓氏, 年份"],
  "filters": {"source_type": "primary", "region": "加利西亚", "subfield": "经济史", "stance": "衰落论", "lang": "德文"},
  "gold_points": ["要点1", "要点2"],
  "note": "出题意图"
}
```

- `filters` 可省略或只填部分键；对应 `corpus_lib.search_chunks` 的过滤参数。
- `expected_titles` 必须是**库内已有的精确书名**（可用 `python db_check.py` 或
  文献库管理页确认哪些书在库中；用 `db_check.py --json` 看 missing_in_db 避免选题出错）。
- `gold_points` 只在 full 模式的裁判环节使用。

## 已知边界

- 检索与 app.py 共用 `corpus_lib.search_chunks`（A7混合+A8精排+A9改写），
  结果可直接对比线上行为；`--baseline` 可回到增强前的纯向量基线。
- 检索端没有做范围锁定（`detect_scope_title`）——app 普通模式会程序化锁定单书，
  评估的期望书目是按"未锁定"口径标注的。
- full 模式的生成是"单次检索 + 一次生成"（对应 app 普通模式），不模拟深度分析模式
  （程序化检索计划 + 多轮工具调用）。
- 引用页码目前为 PDF 页码（项目已知问题），因此 `page_supported` 只验证
  "回答标注的页码 = 片段 citation 里的页码"，不验证印刷页码的真实性。
