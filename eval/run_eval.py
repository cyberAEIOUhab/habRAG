"""
eval/run_eval.py —— habRAG 评估脚本（本次新增，不改动 app.py）

两种模式：
  retrieval（默认）：只做检索，不调用 DeepSeek 生成。指标：
    - title_hit    : 期望书目是否进入 top-k（k 默认 15）
    - first_rank   : 第一本期望书目最早出现在第几位
    - MRR          : 期望书目的平均倒数排名
    - citation_hit : 期望的 (作者姓氏, 年份) 是否出现在返回片段的 citation 字段中
  full：检索 + 模拟 app.py 普通模式生成回答（DeepSeek），再评估：
    - citation_support : 回答中每个 (作者, 年份, p.X) 引用能否在候选池找到依据
      （page_supported / author_year_supported / author_year_only / unsupported）
    - judge            : 用 DeepSeek 当裁判，对照 gold_points 检查覆盖与编造，给 1-5 分
  ⚠️ full 模式会消耗 DeepSeek API 额度，默认 --limit 3，请自行控制。

用法（在项目根目录执行）：
  python -X utf8 eval/run_eval.py                              # retrieval 模式跑全部题
  python -X utf8 eval/run_eval.py --baseline                   # 关闭A7/A8/A9增强，测旧基线
  python -X utf8 eval/run_eval.py --mode full --limit 3        # 生成+裁判，最多3题
  python -X utf8 eval/run_eval.py --limit 5 --k 20             # 前5题，top-k=20
  python -X utf8 eval/run_eval.py --questions eval/other.json  # 换题库
  python -X utf8 eval/run_eval.py --out eval/my_result.json    # 指定结果文件

说明：检索默认走与 app.py 完全同源的增强管线（corpus_lib.search_chunks，
A9改写+A7混合+A8精排）；其中查询改写会对含中文的题多一次小额度DeepSeek调用，
--baseline 模式完全免费（纯向量检索，即增强前的旧行为）。

结果默认写入 eval/results_<时间戳>.json，同时在终端打印汇总表。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import corpus_lib
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_QUESTIONS = os.path.join(EVAL_DIR, "questions.json")

# full 模式的生成提示词：模拟 app.py 普通模式的引用规范（简化版）
FULL_SYSTEM_PROMPT = (
    "你是奥匈帝国历史研究助手（评估脚本模拟普通模式）。请基于提供的史料片段回答问题：\n"
    "- 以转述为主，不要大段照搬原文\n"
    "- 每处引用使用 (作者姓氏, 年份, p. 页码) 格式；片段没有页码时只写 (作者, 年份)，不要编造页码\n"
    "- 严格区分史料直接支持的论断 / 可推断的内容 / 史料未涉及的内容\n"
    "- 用中文回答，专有名词保留原文"
)

# 引用标注匹配：(作者, 年份) 或 (作者, 年份, p. 页码/范围)
CIT_RE = re.compile(
    r"\(([^()]{1,80}?),\s*(1[89]\d{2}|20\d{2})(?:\s*,\s*p\.?\s*(\d+(?:[–\-]\d+)?))?\)"
)


# ============================================================
# DeepSeek 调用（app.py call_deepseek 的移植版）
# ============================================================
def call_deepseek(messages, system_prompt="", temperature=0.3):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "temperature": temperature,
        "messages": (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        ) + messages,
        "max_tokens": 64000,
    }
    try:
        response = requests.post(
            f"{DEEPSEEK_API_URL}/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "API 请求超时"}
    except Exception as e:
        return {"error": f"API 调用失败：{e}"}


# ============================================================
# 检索评估
# ============================================================
def run_retrieval(q, k, baseline=False):
    """对单题执行检索并计算命中指标。baseline=True时关闭A7/A8/A9增强。"""
    filters = q.get("filters") or {}
    try:
        chunks = corpus_lib.search_chunks(
            query=q["question"], n_results=k,
            source_type=filters.get("source_type"),
            region=filters.get("region"),
            lang=filters.get("lang"),
            subfield=filters.get("subfield"),
            stance=filters.get("stance"),
            title=filters.get("title"),
            use_hybrid=not baseline,
            use_rerank=not baseline,
            use_rewrite=not baseline,
        )
    except Exception as e:
        return {"error": str(e)}

    returned_titles = [c.get("title") for c in chunks]
    pool_citations = [c.get("citation", "") for c in chunks]

    title_hits = {}
    first_rank = None
    for t in q.get("expected_titles", []):
        ranks = [i + 1 for i, rt in enumerate(returned_titles) if rt == t]
        title_hits[t] = {"hit": bool(ranks), "first_rank": min(ranks) if ranks else None,
                         "count": len(ranks)}
        if ranks and (first_rank is None or min(ranks) < first_rank):
            first_rank = min(ranks)

    citation_hits = {}
    for cit in q.get("expected_citations", []):
        author_year = cit.lower()
        citation_hits[cit] = any(author_year in pc.lower() for pc in pool_citations)

    top_chunks = [
        {"rank": i + 1, "chunk_id": c.get("chunk_id"), "citation": c.get("citation"),
         "relevance": c.get("relevance")}
        for i, c in enumerate(chunks[:5])
    ]

    return {
        "top_chunks": top_chunks,
        "returned_titles": returned_titles[:k],
        "title_hits": title_hits,
        "citation_hits": citation_hits,
        "first_rank": first_rank,
    }


# ============================================================
# full 模式：生成回答 + 引用支撑检查 + 裁判
# ============================================================
def generate_answer(question, chunks):
    """模拟 app.py 普通模式：检索片段 + 问题 → 一次生成。"""
    context = "\n\n".join(f"[{c.get('citation','?')}]\n{c.get('text','')}" for c in chunks)
    messages = [{
        "role": "user",
        "content": f"史料片段：\n{context}\n\n问题：{question}",
    }]
    resp = call_deepseek(messages, system_prompt=FULL_SYSTEM_PROMPT, temperature=0.3)
    if "error" in resp:
        return None, resp["error"]
    return resp.get("choices", [{}])[0].get("message", {}).get("content", ""), None


def extract_citations(answer):
    """从回答中提取 (作者, 年份[, p. 页码]) 引用标注。"""
    text = (answer or "").replace("，", ",")
    out = []
    for m in CIT_RE.finditer(text):
        out.append({"author": m.group(1).strip(), "year": m.group(2), "page": m.group(3)})
    return out


def check_citation_support(citations, pool_citations):
    """判断每个引用标注能否在候选片段池的citation字段找到依据。"""
    results = []
    for c in citations:
        author_l = c["author"].lower()
        matched = [pc for pc in pool_citations if author_l in pc.lower() and c["year"] in pc]
        if not matched:
            status = "unsupported"
        elif c["page"]:
            page_ok = any(re.search(rf"p\.\s*{re.escape(c['page'])}\b", pc) for pc in matched)
            status = "page_supported" if page_ok else "author_year_only"
        else:
            status = "author_year_supported"
        results.append({**c, "status": status})
    return results


def judge_answer(question, gold_points, answer):
    """用 DeepSeek 当裁判：对照 gold_points 评估回答质量，返回解析后的JSON。"""
    gold_text = "\n".join(f"- {p}" for p in (gold_points or []))
    prompt = (
        "以下是评估问题、参考答案要点和一份待评估的回答。\n\n"
        f"问题：{question}\n\n"
        f"参考答案要点：\n{gold_text}\n\n"
        f"待评估回答：\n{answer}\n\n"
        "请完成评估并严格按JSON返回（不要输出JSON之外的文字）：\n"
        '{"covered": ["回答覆盖到的要点原文"], '
        '"problems": ["回答中与要点矛盾或明显编造的内容", "没有则填null"], '
        '"score": 1到5的整数总体质量分}\n'
        "注意：covered 列要点时尽量沿用要点原文；problems 没有问题时填 null。"
    )
    resp = call_deepseek([{"role": "user", "content": prompt}], temperature=0)
    if "error" in resp:
        return {"error": resp["error"]}
    raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"error": f"裁判返回无法解析：{raw[:200]}"}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return {"error": f"裁判JSON解析失败：{e} | 原始：{raw[:200]}"}


def run_full(q, k, baseline=False):
    """检索 + 生成 + 引用支撑检查 + 裁判，返回完整单题结果。"""
    result = {"retrieval": run_retrieval(q, k, baseline=baseline)}
    if "error" in result["retrieval"]:
        return result

    filters = q.get("filters") or {}
    chunks = corpus_lib.search_chunks(
        query=q["question"], n_results=k,
        source_type=filters.get("source_type"),
        region=filters.get("region"),
        lang=filters.get("lang"),
        subfield=filters.get("subfield"),
        stance=filters.get("stance"),
        title=filters.get("title"),
        use_hybrid=not baseline,
        use_rerank=not baseline,
        use_rewrite=not baseline,
    )
    pool_citations = [c.get("citation", "") for c in chunks]

    answer, err = generate_answer(q["question"], chunks)
    if err:
        result["answer"] = {"error": err}
        return result
    result["answer"] = {"text": answer, "extracted_citations": extract_citations(answer),
                        "citation_support": check_citation_support(
                            extract_citations(answer), pool_citations)}

    result["judge"] = judge_answer(q["question"], q.get("gold_points"), answer)
    return result


# ============================================================
# 汇总与主流程
# ============================================================
def summarize(question_results, mode):
    summary = {"mode": mode, "questions_run": len(question_results)}
    if not question_results:
        return summary

    total_exp_titles = total_hit_titles = 0
    total_exp_cits = total_hit_cits = 0
    mrr_sum = first_rank_values = 0
    for r in question_results:
        ret = r.get("retrieval") or {}
        th = ret.get("title_hits") or {}
        total_exp_titles += len(th)
        total_hit_titles += sum(1 for v in th.values() if v.get("hit"))
        for v in th.values():
            if v.get("first_rank"):
                mrr_sum += 1.0 / v["first_rank"]
                first_rank_values += 1
        ch = ret.get("citation_hits") or {}
        total_exp_cits += len(ch)
        total_hit_cits += sum(1 for v in ch.values() if v)

    summary["title_hit_rate"] = round(total_hit_titles / total_exp_titles, 3) if total_exp_titles else None
    summary["citation_hit_rate"] = round(total_hit_cits / total_exp_cits, 3) if total_exp_cits else None
    summary["mrr"] = round(mrr_sum / first_rank_values, 3) if first_rank_values else None

    if mode == "full":
        n_supported = n_unsupported = 0
        judge_scores = []
        for r in question_results:
            ans = r.get("answer") or {}
            for s in (ans.get("citation_support") or []):
                if s["status"] == "unsupported":
                    n_unsupported += 1
                else:
                    n_supported += 1
            j = r.get("judge") or {}
            if isinstance(j.get("score"), (int, float)):
                judge_scores.append(j["score"])
        summary["citation_support_rate"] = round(
            n_supported / (n_supported + n_unsupported), 3) if (n_supported + n_unsupported) else None
        summary["mean_judge_score"] = round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None
    return summary


def print_summary(summary):
    print("\n" + "=" * 70)
    print(f"汇总（模式={summary.get('mode')}，题数={summary.get('questions_run')}）")
    if summary.get("title_hit_rate") is not None:
        print(f"  期望书目命中率    : {summary['title_hit_rate']}")
    if summary.get("citation_hit_rate") is not None:
        print(f"  期望引用命中率    : {summary['citation_hit_rate']}")
    if summary.get("mrr") is not None:
        print(f"  MRR（期望书目）   : {summary['mrr']}")
    if summary.get("citation_support_rate") is not None:
        print(f"  回答引用支撑率    : {summary['citation_support_rate']}")
    if summary.get("mean_judge_score") is not None:
        print(f"  裁判平均分(1-5)   : {summary['mean_judge_score']}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="habRAG 评估脚本")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="问题集JSON路径")
    parser.add_argument("--mode", choices=["retrieval", "full"], default="retrieval",
                        help="retrieval=只检索；full=检索+生成+引用检查+裁判（消耗DeepSeek额度）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前N题，0=全部")
    parser.add_argument("--k", type=int, default=15, help="top-k，默认15（与app普通模式一致）")
    parser.add_argument("--baseline", action="store_true",
                        help="关闭A7混合检索/A8精排/A9改写，测量增强前的旧基线")
    parser.add_argument("--out", default=None, help="结果JSON输出路径（默认 eval/results_<时间戳>.json）")
    args = parser.parse_args()

    with open(args.questions, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", [])
    if args.limit > 0:
        questions = questions[: args.limit]

    print(f"题库：{args.questions}（共{len(questions)}题，模式={args.mode}，k={args.k}，"
          f"baseline={args.baseline}）")

    results = []
    for i, q in enumerate(questions):
        print(f"\n[{i + 1}/{len(questions)}] {q['id']} · {q['question'][:60]}...")
        t0 = time.time()
        if args.mode == "full":
            r = run_full(q, args.k, baseline=args.baseline)
        else:
            r = {"retrieval": run_retrieval(q, args.k, baseline=args.baseline)}
        r["elapsed_sec"] = round(time.time() - t0, 1)
        ret = r.get("retrieval") or {}
        if ret.get("error"):
            print(f"  ❌ 检索失败：{ret['error']}")
        else:
            for t, v in (ret.get("title_hits") or {}).items():
                mark = "✅" if v["hit"] else "❌"
                rank = f"第{v['first_rank']}位" if v["first_rank"] else "未命中"
                print(f"  {mark} 书目 {t[:60]} → {rank}")
            for cit, ok in (ret.get("citation_hits") or {}).items():
                print(f"  {'✅' if ok else '❌'} 引用 {cit}")
        if args.mode == "full":
            ans = r.get("answer") or {}
            if ans.get("error"):
                print(f"  ❌ 生成失败：{ans['error']}")
            else:
                sup = ans.get("citation_support") or []
                print(f"  🔎 提取引用 {len(sup)} 处："
                      f"完整支撑 {sum(1 for s in sup if s['status']=='page_supported')}，"
                      f"仅作者年份 {sum(1 for s in sup if s['status'] in ('author_year_supported','author_year_only'))}，"
                      f"无依据 {sum(1 for s in sup if s['status']=='unsupported')}")
                j = r.get("judge") or {}
                if j.get("error"):
                    print(f"  ⚠️ 裁判失败：{j['error']}")
                else:
                    print(f"  🧑‍⚖️ 裁判评分：{j.get('score')} | 覆盖要点 {len(j.get('covered') or [])} 个"
                          f" | 问题 {len(j.get('problems') or [])} 处")
        results.append({"id": q["id"], "question": q["question"], **r})

    summary = summarize(results, args.mode)
    print_summary(summary)

    out_path = args.out or os.path.join(EVAL_DIR, f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "questions_file": os.path.basename(args.questions),
        "mode": args.mode,
        "k": args.k,
        "baseline": args.baseline,
        "summary": summary,
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入：{out_path}")


if __name__ == "__main__":
    main()
