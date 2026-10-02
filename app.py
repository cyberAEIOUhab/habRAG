"""
app.py —— 奥匈帝国史研究助手（重构版）

相对旧版的主要变化：
1. chunk metadata不再存author/year/filename，只存title作为关联键；
   author/year/publisher/description等书目信息统一从bookdata.json反查
2. embedding从本地Ollama(nomic-embed-text)换成SiliconFlow云端API(bge-m3)
3. search_corpus与原search_by_stance合并为一个函数，新增subfield/stance过滤参数
4. chunk_id格式从 filename::chunk_index 改为 title::chunk_index
5. 新增 exclude_chunks 工具：session级软排除，让agent可以把判断为噪声/无关的
   片段临时排除出后续检索结果（清空对话后自动重置，不是永久删除）
6. 新增 list_books_by_filter 工具：纯结构化过滤书目，不依赖语义检索
7. 新增回答生成后的引用校验步骤（不是agent可调用的工具，是流程里硬编码的一步）
8. 回答引用格式分两类：二手著作与回忆录为 (作者, 年份, p. 页码)；档案汇编类（ÖUA、MRP
   等带 doc_number 的 chunk）为「卷次, Nr. 编号」，如 ÖUA VIII, Nr. 10364。实现统一在
   corpus_lib.format_citation_tag（app.py 不再保留副本，避免两份实现产生格式分歧）；
   展开面板信息来源统一标注为 "从bookdata.json提取"
9. 新增开发者模式开关（侧边栏）：开启后可查看agent每一步的模型输入/输出、
   工具调用参数与返回结果（范围识别、检索、生成、引用校验等全流程轨迹），
   轨迹随对话历史保存，默认折叠，不影响正常使用
10. 检索增强（A组）：中文问题自动改写为多语言查询(A9) + 向量/全文RRF混合检索(A7)
    + bge-reranker-v2-m3精排(A8)。实现在corpus_lib.search_chunks（与eval同源），
    开关在config.py（HYBRID_SEARCH_ENABLED / RERANK_ENABLED / QUERY_REWRITE_ENABLED）
11. 深度模式新增程序化检索计划步骤(A10)：进入工具循环前先让模型制定检索计划并自动执行
12. 侧边栏新增检索过滤控件(A11)：普通模式直接生效，深度模式硬覆盖模型传的同类参数
13. 引用校验升级为"引用↔片段映射"(A13)：回答下方显示引用对照表，随历史保存
14. 新增：导出Markdown(A14)、流式输出(A15)、对话持久化多会话(A16，sources只存
    chunk_id不存全文，渲染时按id从库还原)、API错误显性化(A17)、每步计时(A24)、
    点赞反馈(A26，写入feedback.jsonl)
15. 新增长文本分析模式（侧边栏开关）：两个输入框（长文本 + 分析要求/备注），
    三阶段台账式流程——阶段一分解论点 → 阶段二逐论点核查（record_verdict工具、
    expand_chunk溯源二手论据、一手史料多通道识别[source_type标签不可信]）→
    阶段三综合报告。总体不设工具调用上限，每论点内置20次护栏；台账存session不落盘；
    跳过范围锁定/A10计划/侧边栏过滤；展示只收敛到被引用片段（上限30条）
16. 新增Light模式（终端启动：streamlit run app.py -- -light）：界面与功能完全不变，
    主任务模型 deepseek-v4-pro→deepseek-v4-flash，引用核对/排版修正改用完全免费的
    glm-4.7-flash（config.py 中 GLM_* 配置）
"""

import os
import re
import json
import sys
import time

import streamlit as st
import chromadb
import requests

from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, DEEPSEEK_MODEL_LIGHT,
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, EMBEDDING_MODEL,
    CHROMA_DB_PATH,
    HYBRID_SEARCH_ENABLED, QUERY_REWRITE_ENABLED, RERANK_ENABLED,
    GLM_API_KEY, GLM_BASE_URL, GLM_MODEL,
)

from corpus_lib import (correct_units, format_citation_tag, get_chunks_by_ids,
                        get_collection, get_corrected_text, search_chunks)

# ============================================================
# Light模式：streamlit run app.py -- -light
# 所有原本用 deepseek-v4-pro 的主任务改用 deepseek-v4-flash；
# 引用核对/排版修正等轻任务改用完全免费的 glm-4.7-flash。
# 界面与功能完全不变，只是模型分配不同。
# ============================================================
LIGHT_MODE = any(a in ("-light", "--light") for a in sys.argv)
MAIN_MODEL = DEEPSEEK_MODEL_LIGHT if LIGHT_MODE else DEEPSEEK_MODEL

st.set_page_config(page_title="奥匈帝国史研究助手", layout="wide")
st.title("奥匈帝国史研究助手")
if LIGHT_MODE:
    st.caption(f"⚡ Light 模式已启用（主模型 {MAIN_MODEL}，核对/排版使用免费 {GLM_MODEL}）")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKDATA_PATH = os.path.join(PROJECT_DIR, "bookdata.json")
COLLECTION_NAME = "habsburg"
SESSIONS_DIR = os.path.join(PROJECT_DIR, "sessions")
FEEDBACK_PATH = os.path.join(PROJECT_DIR, "feedback.jsonl")

REGION_CANDIDATES = [
    "全帝国",
    "下奥地利", "上奥地利", "萨尔茨堡", "施泰尔马克", "克恩顿", "克赖恩",
    "蒂罗尔-福拉尔贝格", "滨海地区", "波希米亚", "摩拉维亚", "奥属西里西亚",
    "加利西亚", "布科维纳", "达尔马提亚",
    "匈牙利本土", "特兰西瓦尼亚", "克罗地亚-斯拉沃尼亚", "斯洛伐克地区",
    "伏伊伏丁那/巴纳特", "阜姆",
    "波斯尼亚-黑塞哥维那",
    "德意志地区", "巴尔干地区", "奥斯曼帝国", "俄罗斯帝国", "意大利", "波兰",
]
SUBFIELD_CANDIDATES = [
    "政治史", "外交史", "经济史", "军事史", "社会史", "民族史", "地区研究", "犹太史",
]
STANCE_CANDIDATES = ["衰落论", "修正主义", "中立描述", "不涉及该争论"]
SOURCE_TYPE_CANDIDATES = ["primary", "secondary", "mixed"]

MAX_TOOL_CALLS = 50
MAX_HISTORY_TURNS = 6

# 开发者模式相关
DEV_LOG_MAX_ENTRIES = 300   # 单次问答最多记录多少步，防止轨迹无限膨胀
DEV_CLIP_CHARS = 4000       # 单条日志正文的展示上限
DEV_CLIP_MSG = 1200         # 输入messages中每条消息内容的展示上限


def _clip(text, limit=DEV_CLIP_CHARS):
    s = str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n\n…（内容过长已截断，完整长度 {len(s)} 字符）"


def dev_record(title, text, is_json=False, elapsed=None):
    """向本次问答的开发者轨迹追加一步（输入/输出快照，可带耗时，A24）"""
    if "dev_log" not in st.session_state:
        st.session_state.dev_log = []
    if len(st.session_state.dev_log) >= DEV_LOG_MAX_ENTRIES:
        return
    entry = {"title": title, "text": _clip(str(text)), "is_json": is_json}
    if elapsed is not None:
        entry["elapsed"] = round(float(elapsed), 2)
    st.session_state.dev_log.append(entry)


def render_dev_log(logs=None):
    """渲染开发者轨迹（嵌套折叠面板，默认全部收起，不影响正常使用）"""
    if logs is None:
        logs = st.session_state.get("dev_log", [])
    if not logs:
        return
    with st.expander(f"🧪 开发者模式 · 执行轨迹（共{len(logs)}步）"):
        for i, entry in enumerate(logs):
            title_txt = entry["title"]
            if entry.get("elapsed") is not None:
                title_txt += f"（{entry['elapsed']}s）"
            with st.expander(f"第{i+1}步 · {title_txt}"):
                st.code(entry["text"], language="json" if entry["is_json"] else None)


# ============================================================
# 单例资源
# ============================================================
# ★ 不要在这里直接建 Chroma 客户端 —— 那会绕过 config.BACKEND 的后端开关，
#   导致 HABRAG_BACKEND=zilliz 时界面仍读本地库。
#   get_collection 现由 corpus_lib 提供（文件顶部 import），内部按 BACKEND 分派
#   （chroma / zilliz），并自带进程内单例与锁，跨 Streamlit rerun 有效。
#   （chromadb / CHROMA_DB_PATH 的 import 保留未删，仅为兼容，不再使用。）


@st.cache_resource
def get_bookdata_lookup():
    """title -> bookdata.json条目 的查找字典，author/year/publisher/description等权威信息来源"""
    with open(BOOKDATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {b["title"]: b for b in data}


def get_book_meta(title):
    """按title反查bookdata.json，找不到时返回一份占位数据而不是报错"""
    lookup = get_bookdata_lookup()
    meta = lookup.get(title)
    if meta is None:
        return {"title": title, "author": "未知", "year": "未知",
                "publisher": None, "description": None, "language": "未知"}
    return meta


# ============================================================
# Embedding（SiliconFlow bge-m3）
# ============================================================
def embed_text(text, retries=3):
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": EMBEDDING_MODEL, "input": [text], "encoding_format": "float"}
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{SILICONFLOW_BASE_URL}/embeddings",
                headers=headers, json=payload, timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"embedding调用失败（已重试{retries}次）：{last_err}")


# ============================================================
# 模型调用（light模式自动切换模型档案）
# ============================================================
def call_deepseek(messages, system_prompt="", tools=None, temperature=0.3,
                  model=None, api_key=None, base_url=None):
    """通用OpenAI兼容chat调用。默认MAIN_MODEL（light模式=flash），可覆盖为glm等。"""
    headers = {
        "Authorization": f"Bearer {api_key or DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or MAIN_MODEL,
        "temperature": temperature,
        "messages": (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        ) + messages,
        "max_tokens": 64000,  # DeepSeek V4系列输出上限384000，这里留足学术长回答的空间，同时不过度浪费
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        response = requests.post(
            f"{base_url or DEEPSEEK_API_URL}/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "API 请求超时"}
    except Exception as e:
        return {"error": f"API 调用失败：{e}"}


def _check_call(messages, temperature=0):
    """引用核对（postprocess）专用：light模式用免费glm，普通模式用pro。"""
    if LIGHT_MODE:
        return call_deepseek(messages, temperature=temperature,
                             model=GLM_MODEL, api_key=GLM_API_KEY, base_url=GLM_BASE_URL)
    return call_deepseek(messages, temperature=temperature)


def call_deepseek_stream(messages, system_prompt="", temperature=0.3):
    """流式调用（A15），逐段yield回答文本；异常在流内附错误提示。light模式自动用flash。"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MAIN_MODEL,
        "temperature": temperature,
        "messages": (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        ) + messages,
        "max_tokens": 64000,
        "stream": True,
    }
    try:
        with requests.post(
            f"{DEEPSEEK_API_URL}/chat/completions",
            headers=headers, json=payload, stream=True, timeout=300,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
    except requests.exceptions.Timeout:
        yield "\n\n⚠️ 生成超时（已显示的部分为超时前内容）"
    except Exception as e:
        yield f"\n\n⚠️ 流式生成中断：{e}"


# ============================================================
# 引用格式化
# 说明：format_citation_tag 已统一到 corpus_lib（避免两份实现产生格式分歧）。
# 档案汇编类由 corpus_lib 按「卷次, Nr. 编号」输出，其余仍为 (作者, 年份, p. 页码)。
# ============================================================
def enrich_chunk(chunk_meta, text, relevance=None):
    """把chunk metadata和bookdata.json信息合并成一份完整的展示用字典"""
    book = get_book_meta(chunk_meta["title"])
    out = {
        "chunk_id": f"{chunk_meta.get('title','?')}::{chunk_meta.get('chunk_index','?')}",
        "chunk_index": chunk_meta.get("chunk_index"),
        "title": chunk_meta.get("title", "未知"),
        "source": chunk_meta.get("title", "未知"),  # 出处：书名，供展开面板显眼展示
        "author": book.get("author", "未知"),
        "year": book.get("year", "未知"),
        "publisher": book.get("publisher"),
        "page_num": chunk_meta.get("page_num"),
        "chapter_title": chunk_meta.get("chapter_title") or None,
        "stance": chunk_meta.get("stance"),
        "subfield": chunk_meta.get("subfield"),
        "period": chunk_meta.get("period"),
        "region": chunk_meta.get("region"),
        "source_type": chunk_meta.get("source_type"),
        "language": chunk_meta.get("language"),
        "doc_number": chunk_meta.get("doc_number"),
        "doc_date": chunk_meta.get("doc_date"),
        "doc_section": chunk_meta.get("doc_section"),
        "doc_part": chunk_meta.get("doc_part"),
        "citation": format_citation_tag(chunk_meta, text),
        "text": text,
    }
    if relevance is not None:
        out["relevance"] = relevance
    return out


# ============================================================
# 工具实现
# ============================================================
def _excluded_ids():
    return st.session_state.get("excluded_chunk_ids", set())


def tool_search_corpus(query, source_type=None, region=None, lang=None,
                        subfield=None, stance=None, title=None, n_results=10):
    """
    语义检索史料库（合并了原search_corpus + search_by_stance）。
    支持按source_type/region/lang/subfield/stance/title任意组合过滤；region/subfield
    支持多值列表（任一匹配，A11侧边栏多选用）。
    底层为corpus_lib.search_chunks：A9查询改写 + A7向量/全文RRF + A8 rerank精排。
    title用于把检索范围锁定在单一书目内（当用户问题明确限定某本书时使用）。
    """
    debug_log = None
    if st.session_state.get("dev_mode_on"):
        def debug_log(d):
            dev_record(d["title"], d["text"], d["is_json"])

    return search_chunks(
        query=query, source_type=source_type, region=region, lang=lang,
        subfield=subfield, stance=stance, title=title, n_results=n_results,
        excluded=_excluded_ids(),
        use_hybrid=HYBRID_SEARCH_ENABLED, use_rerank=RERANK_ENABLED,
        use_rewrite=QUERY_REWRITE_ENABLED, debug_log=debug_log,
    )


def tool_expand_chunk(chunk_id, window=2):
    """扩展某片段的上下文，返回前后window个片段"""
    collection = get_collection()
    try:
        title, chunk_index = chunk_id.rsplit("::", 1)
        chunk_index = int(chunk_index)
    except Exception:
        return {"error": f"无效的chunk_id格式：{chunk_id}，应为 title::chunk_index"}

    result = collection.get(
        where={
            "$and": [
                {"title": {"$eq": title}},
                {"chunk_index": {"$gte": chunk_index - window}},
                {"chunk_index": {"$lte": chunk_index + window}},
            ]
        },
        include=["documents", "metadatas"],
    )

    excluded = _excluded_ids()
    pairs = sorted(
        zip(result["documents"], result["metadatas"]),
        key=lambda x: x[1].get("chunk_index", 0),
    )

    output = []
    for doc, meta in pairs:
        cid = f"{meta.get('title','?')}::{meta.get('chunk_index','?')}"
        if cid in excluded:
            continue
        item = enrich_chunk(meta, doc)
        item["is_target"] = meta.get("chunk_index") == chunk_index
        output.append(item)
    return output


def tool_get_book_info(title=None, author=None):
    """获取某本书的元数据（来自bookdata.json），包括简介"""
    if not title and not author:
        return {"error": "请提供title或author参数"}

    lookup = get_bookdata_lookup()

    match = None
    if title:
        match = lookup.get(title)
        if match is None:
            # 部分匹配兜底
            for t, b in lookup.items():
                if title in t or t in title:
                    match = b
                    break
    if match is None and author:
        for b in lookup.values():
            book_author = b.get("author") or ""
            if author in book_author:
                match = b
                break

    if match is None:
        return {"error": f"未找到匹配的书目：{title or author}"}

    collection = get_collection()
    try:
        count_result = collection.get(
            where={"title": {"$eq": match["title"]}}, include=[]
        )
        chunk_count = len(count_result["ids"])
    except Exception:
        chunk_count = "未知"

    return {
        "title": match.get("title"),
        "author": match.get("author"),
        "year": match.get("year"),
        "publisher": match.get("publisher"),
        "language": match.get("language"),
        "page_count": match.get("page_count"),
        "description": match.get("description"),
        "has_bookmarks": match.get("has_bookmarks"),
        "chunk_count": chunk_count,
    }


def tool_list_sources_on_topic(topic, n_results=8):
    """文献侦察：返回与主题相关的书目列表，不返回片段内容"""
    collection = get_collection()
    query_emb = embed_text(topic)

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=n_results * 3,
        include=["metadatas", "distances"],
    )

    seen = {}
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        title = meta.get("title", "")
        relevance = round(1 - dist, 3)
        if title not in seen or relevance > seen[title]["relevance"]:
            book = get_book_meta(title)
            seen[title] = {
                "title": title,
                "author": book.get("author", "未知"),
                "year": book.get("year", "未知"),
                "description": book.get("description"),
                "relevance": relevance,
            }

    sorted_books = sorted(seen.values(), key=lambda x: x["relevance"], reverse=True)
    return sorted_books[:n_results]


def tool_list_books_by_filter(region=None, subfield=None, stance=None, source_type=None):
    """
    纯结构化过滤：按region/subfield/stance/source_type任意组合，返回符合条件的书目列表。
    不做语义检索，用于回答"库里有哪些书是……"这类元问题。
    """
    if not any([region, subfield, stance, source_type]):
        return {"error": "请至少提供一个过滤条件（region/subfield/stance/source_type）"}

    collection = get_collection()
    where_conditions = []
    if region:
        where_conditions.append({"region": {"$contains": region}})
    if subfield:
        where_conditions.append({"subfield": {"$contains": subfield}})
    if stance:
        where_conditions.append({"stance": {"$eq": stance}})
    if source_type:
        where_conditions.append({"source_type": {"$eq": source_type}})

    where = where_conditions[0] if len(where_conditions) == 1 else {"$and": where_conditions}

    result = collection.get(where=where, include=["metadatas"], limit=5000)

    titles = set(m.get("title") for m in result["metadatas"] if m.get("title"))
    books = []
    for t in titles:
        book = get_book_meta(t)
        books.append({"title": t, "author": book.get("author"), "year": book.get("year")})
    books.sort(key=lambda x: (x.get("year") or ""))
    return books


def tool_exclude_chunks(chunk_ids, reason=""):
    """
    把指定chunk_id加入本次对话的排除集合，之后search_corpus/expand_chunk不再返回它们。
    仅在本次对话有效，点击"清空对话"后自动重置，不是永久删除。
    """
    if "excluded_chunk_ids" not in st.session_state:
        st.session_state.excluded_chunk_ids = set()
    st.session_state.excluded_chunk_ids.update(chunk_ids)
    return {
        "excluded_count": len(chunk_ids),
        "total_excluded_this_session": len(st.session_state.excluded_chunk_ids),
        "reason": reason,
    }


# ============================================================
# 工具分派
# ============================================================
def detect_scope_title(question):
    """
    程序化识别：问题是否把讨论范围明确限定在单一书目内。
    识别信号：《书名》/引号内容精确或高度匹配bookdata.json中的title，或作者姓氏被提及。
    只有能唯一确定一本书时才返回title；存在歧义（比如姓氏对应多本书）时返回None，
    不强行锁定——宁可不锁，也不要锁错。
    这是一道代码层面的硬约束：锁定后，检索工具物理上拿不到范围外的内容，
    不依赖模型是否"愿意"遵守问题里的限定。
    """
    lookup = get_bookdata_lookup()
    q = question.strip()

    # 信号1：《书名》或引号内容，与bookdata.json中的title精确/高度匹配
    quoted = re.findall(r"《([^》]+)》|[\"'“”‘’]([^\"'“”‘’]{4,})[\"'“”‘’]", q)
    quoted_texts = [a or b for a, b in quoted]
    title_matches = set()
    for qt in quoted_texts:
        qt_norm = qt.strip().lower()
        if not qt_norm:
            continue
        for title in lookup:
            t_norm = title.lower()
            if qt_norm == t_norm or qt_norm in t_norm or t_norm in qt_norm:
                title_matches.add(title)

    # 信号2：作者姓氏在问题中被提及（要求词边界匹配，避免误命中短姓氏子串）
    author_matches = set()
    for title, book in lookup.items():
        author = (book.get("author") or "").strip()
        if not author:
            continue
        surname = author.split()[-1].strip(",") if author.split() else author
        if len(surname) >= 3 and re.search(r"\b" + re.escape(surname) + r"\b", q, re.IGNORECASE):
            author_matches.add(title)

    # 两个信号都命中且交集为1本书时最可信；否则任一信号单独命中唯一1本书也锁定
    if title_matches and author_matches:
        combined = title_matches & author_matches
        if len(combined) == 1:
            return next(iter(combined))
    candidates = title_matches or author_matches
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def ui_filters():
    """侧边栏选中的检索过滤条件（A11）；空值不返回，供普通模式透传与深度模式硬覆盖。"""
    f = st.session_state.get("ui_filters", {}) or {}
    return {k: v for k, v in f.items() if v}


def execute_tool(name, args, scope_title=None, apply_ui_filters=True):
    """
    scope_title非None时，代表本轮问题已被程序化识别为限定单一书目——
    这里做的是硬性覆盖/拒绝，不是"建议"，不依赖模型是否遵守。
    侧边栏过滤条件（A11）同样硬覆盖模型传的同类参数；
    apply_ui_filters=False 时长文本模式不使用侧边栏过滤（需要全库视野）。
    """
    try:
        if name == "search_corpus":
            # 范围锁定时强制覆盖title，不管模型传了什么（包括没传、传错、传了别的书）
            effective_title = scope_title if scope_title else args.get("title")
            # 侧边栏过滤条件：用户显式选择时硬覆盖模型传的同类参数
            if apply_ui_filters:
                uf = ui_filters()
                if uf.get("source_type"):
                    args["source_type"] = uf["source_type"]
                if uf.get("region"):
                    args["region"] = uf["region"]
                if uf.get("subfield"):
                    args["subfield"] = uf["subfield"]
                if uf.get("stance"):
                    args["stance"] = uf["stance"]
                if uf.get("lang"):
                    args["lang"] = uf["lang"]
            result = tool_search_corpus(
                query=args["query"],
                source_type=args.get("source_type"),
                region=args.get("region"),
                lang=args.get("lang"),
                subfield=args.get("subfield"),
                stance=args.get("stance"),
                title=effective_title,
                n_results=args.get("n_results", 10),
            )
        elif name == "expand_chunk":
            chunk_id = args["chunk_id"]
            if scope_title and not chunk_id.startswith(f"{scope_title}::"):
                # 范围锁定时，拒绝扩展锁定书目之外的chunk（正常情况下也不该出现，
                # 因为search_corpus已经被锁定，这里是防御性的第二道防线）
                return json.dumps(
                    {"error": f"本轮问题已限定范围为《{scope_title}》，不能扩展该书之外的片段"},
                    ensure_ascii=False,
                )
            result = tool_expand_chunk(
                chunk_id=chunk_id, window=args.get("window", 2)
            )
        elif name == "get_book_info":
            result = tool_get_book_info(
                title=args.get("title"), author=args.get("author")
            )
        elif name == "list_sources_on_topic":
            result = tool_list_sources_on_topic(
                topic=args["topic"], n_results=args.get("n_results", 8)
            )
        elif name == "list_books_by_filter":
            result = tool_list_books_by_filter(
                region=args.get("region"),
                subfield=args.get("subfield"),
                stance=args.get("stance"),
                source_type=args.get("source_type"),
            )
        elif name == "exclude_chunks":
            result = tool_exclude_chunks(
                chunk_ids=args["chunk_ids"], reason=args.get("reason", "")
            )
        else:
            result = {"error": f"未知工具：{name}"}

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ============================================================
# 工具定义（发给DeepSeek的schema）
# ============================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_corpus",
            "description": (
                "在史料库中进行语义检索，返回相关片段。可按来源类型、地区、语言、"
                "学科视角(subfield)、史学立场(stance)任意组合过滤。需要平衡不同学派"
                "观点时，分别用不同的stance参数调用两次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询，使用英文效果更好"},
                    "source_type": {
                        "type": "string", "enum": SOURCE_TYPE_CANDIDATES,
                        "description": "史料类型：primary=一手史料，secondary=二手史学著作，mixed=混合",
                    },
                    "region": {
                        "type": "string", "enum": REGION_CANDIDATES,
                        "description": "地区过滤",
                    },
                    "lang": {
                        "type": "string", "enum": ["英文", "中文", "德文", "匈牙利文", "波兰文", "混合"],
                        "description": "限定检索特定语言的文献",
                    },
                    "subfield": {
                        "type": "string", "enum": SUBFIELD_CANDIDATES,
                        "description": "学科视角过滤",
                    },
                    "stance": {
                        "type": "string", "enum": STANCE_CANDIDATES,
                        "description": "史学立场过滤：衰落论/修正主义/中立描述/不涉及该争论",
                    },
                    "n_results": {"type": "integer", "description": "返回片段数量，默认10，建议5-20"},
                    "title": {
                        "type": "string",
                        "description": (
                            "书名精确匹配（需与库中书名完全一致，可先用get_book_info或"
                            "list_sources_on_topic确认准确书名）。当用户问题明确限定"
                            "只讨论某一本书时必须传入此参数，把检索范围锁定在该书内，"
                            "不要让其他书目的内容混入结果。"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand_chunk",
            "description": "扩展某个片段的上下文，获取该片段在原书中的前后相邻片段。当发现某片段高度相关但内容不完整时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string", "description": "片段ID，格式为 title::chunk_index，从其他工具的返回结果中获取"},
                    "window": {"type": "integer", "description": "向前和向后各取多少个片段，默认2"},
                },
                "required": ["chunk_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_book_info",
            "description": "获取某本书的完整元数据，包括作者、年份、出版社、语言、页数和内容简介。在决定是否深入检索某本书前使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "书名（部分匹配即可）"},
                    "author": {"type": "string", "description": "作者名"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sources_on_topic",
            "description": "文献侦察：返回与主题相关的书目列表（不返回片段内容）。在开始深入检索前，用于了解库中有哪些相关文献。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "主题关键词"},
                    "n_results": {"type": "integer", "description": "返回书目数量，默认8"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_books_by_filter",
            "description": (
                "纯结构化过滤（不做语义检索），按地区/学科视角/史学立场/史料类型任意组合，"
                "返回符合条件的书目列表。适合回答'库里有哪些书是……'这类关于文献库构成本身的问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "enum": REGION_CANDIDATES},
                    "subfield": {"type": "string", "enum": SUBFIELD_CANDIDATES},
                    "stance": {"type": "string", "enum": STANCE_CANDIDATES},
                    "source_type": {"type": "string", "enum": SOURCE_TYPE_CANDIDATES},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exclude_chunks",
            "description": (
                "把明显是噪声（页眉页脚残留、脚注、参考文献列表碎片等）或与当前问题"
                "完全无关、占用检索名额的片段排除出本次对话后续的检索结果。仅本次对话"
                "有效，不是永久删除。当发现某本书返回了大量不相关或低质量片段、挤占了"
                "其他更相关文献的检索名额时，也可以用这个工具排除掉，为后续检索腾出空间。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "要排除的chunk_id列表，格式为 title::chunk_index",
                    },
                    "reason": {"type": "string", "description": "排除原因，便于记录"},
                },
                "required": ["chunk_ids"],
            },
        },
    },
]

# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """你是一位专业的奥匈帝国历史研究助手，拥有访问史料库的工具集。

【工作流程】
0. 系统已在开头自动制定并执行了检索计划（对应tool_call_id为 plan_N 的检索结果）。
   如这些结果已足够，直接基于它们作答；不足时再做补充检索，
   不要重复计划中已执行过的检索
1. 收到问题后，先用 list_sources_on_topic 了解库中有哪些相关文献
2. 根据问题性质决定检索策略：
   - 问题明确限定只讨论某一本书/某位作者的某部著作时：必须在 search_corpus 中
     传入 title 参数锁定检索范围，不要让其他书目的内容混入检索结果、回答或引用中；
     书名不确定时先用 get_book_info 或 list_sources_on_topic 确认准确书名
   - 简单事实性问题：直接用 search_corpus 检索
   - 史学争论问题：必须分别用 search_corpus 指定不同的 stance 参数（如"衰落论"和"修正主义"），
     检索至少两个对立学派的证据，不能只用第一批结果下结论
   - 需要原始文件的问题：用 search_corpus 并指定 source_type=primary
   - 涉及特定地区的问题：用 search_corpus 并指定 region 参数
   - 涉及特定学科视角（如经济史/军事史）的问题：用 search_corpus 并指定 subfield 参数
   - 关于文献库本身构成的问题（如"库里有哪些书讨论加利西亚"）：用 list_books_by_filter，
     不要用语义检索去回答这类结构化问题
3. 发现高度相关但内容不完整的片段时，用 expand_chunk 扩展上下文
4. 如果检索结果中出现明显的噪声片段（页眉页脚残留、脚注碎片、参考文献列表）或者与当前
   问题完全无关但反复占用检索名额的片段，用 exclude_chunks 排除掉，避免它们持续干扰后续检索
5. 判断检索结果是否充分，不充分时换角度或换关键词继续检索
6. 收集到足够证据后，生成最终回答

【史学方法论要求】
- 遇到史学争论问题，必须呈现至少两个学派的观点
- 涉及民族政策、帝国治理问题时，主动检索非匈牙利裔少数民族（斯洛伐克、加利西亚犹太人、
  乌克兰人、波斯尼亚人）的视角，不能默认以马扎尔或维也纳视角为主叙事
- 涉及人口数据、民族构成时，注意1910年人口普查数据的政治性——统计口径受马扎尔化政策
  影响，引用时需说明局限性
- 区分 primary（直接证据）和 secondary（史学解读），引用时明确标注

【回答格式 —— 引用规范】
- 以转述为主：先理解检索到的内容，用你自己的话转述论点，不要大段照搬原文。直接引用
  原文只用于措辞本身有精确论证意义的关键句（比如作者刻意选择的术语、需要保留原文才能
  体现论证力度的句子），每处直接引用控制在一两句话以内，不要把整段原文搬进回答
- 【两类史料，两套引用格式，先看片段自带的 citation 字段长什么样，照着用】
  · 二手史学著作与回忆录：citation 形如「Judson, 2016, p. 45」，直接使用该格式，
    例如 (Judson, 2016, p. 45)。页码必须来自你实际引用/转述的那个具体片段自己的
    citation 字段，不能图省事对同一本书的多处引用都用同一个笼统的 (作者, 年份)，
    除非那个具体片段本身就没有页码
  · 档案汇编类（ÖUA、MRP 等）：citation 形如「ÖUA VIII, Nr. 10364」或
    「MRP 3/8/2, Nr. 220」，一律照此引用（卷次 + Nr. 文件编号），**不要**改写成
    (作者, 年份, p. 页码) 形式。这类片段的正文首部带有 [卷次 · Nr. 编号 · 日期]
    前缀，其中可读出该文件的文种（Erlaß 指令 / Bericht 汇报 / Tel. 电报 /
    Denkschrift 备忘录等）、收发双方与日期，叙述时可直接采用；
    若只引用了某份文件的部分内容，可注明「Nr. 10364，第2/3部分」
- 检索结果中每个片段都附带了 citation 字段（已按上述两类格式生成好），直接使用，不要用
  "片段1"/"片段2"这类编号指代史料
- 如果某片段没有页码（citation中不含"p."，也不是档案编号形制），引用时只写 (作者, 年份)
  即可，不要编造页码
- 严格区分：史料直接支持的论断 / 基于史料的合理推断（标注"可推断"）/ 史料未涉及的内容
  （说明"现有史料不足以回答"）
- 遇到不同史学倾向的矛盾论点，明确指出并分析分歧原因
- 用中文回答，专有名词保留原文并附中文译名"""


# ============================================================
# 检索计划（A10：深度模式程序化计划步骤）
# ============================================================
PLAN_PROMPT_TEMPLATE = """你是检索计划制定者。请为用户问题制定一个精简的史料检索计划。

可用过滤条件：
- source_type: primary（一手史料）/ secondary（二手史学著作）/ mixed
- region: {regions}
- subfield: {subfields}
- stance: 衰落论 / 修正主义 / 中立描述 / 不涉及该争论
- lang: 英文 / 中文 / 德文 / 匈牙利文 / 波兰文 / 混合
- title: 库中精确书名（问题明确限定某一本书时才填，可直接用书名锁定检索范围）

要求：
1. 简单事实性问题给1条检索即可；复杂/多子问题/需对比的问题给2-4条检索
2. 每条检索的query使用英文（效果最好），保留专有名词原文
3. 史学争论问题必须包含至少两条分别指定对立stance（如衰落论与修正主义）的检索
4. 不要输出JSON之外的任何文字，格式：
{{"searches": [{{"query": "...", "purpose": "...", "source_type": null, "region": null, "subfield": null, "stance": null, "lang": null, "title": null}}]}}

问题：{question}"""


def _make_retrieval_plan(question):
    """
    让模型制定检索计划（A10），返回 [(检索参数dict, 目的说明), ...]；失败返回None。
    计划失败不影响主流程（回退为原来的自由工具调用）。
    """
    prompt = PLAN_PROMPT_TEMPLATE.format(
        regions=", ".join(REGION_CANDIDATES),
        subfields=", ".join(SUBFIELD_CANDIDATES),
        question=question,
    )
    try:
        resp = call_deepseek([{"role": "user", "content": prompt}], temperature=0.2)
        if "error" in resp:
            return None
        raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        plan = json.loads(m.group(0))
        searches = plan.get("searches") or []
        out = []
        for s in searches[:4]:
            q = (s.get("query") or "").strip()
            if not q:
                continue
            args = {"query": q, "n_results": 8}
            for k in ("source_type", "region", "subfield", "stance", "lang", "title"):
                v = s.get(k)
                if v:
                    args[k] = v
            out.append((args, (s.get("purpose") or "").strip()))
        return out or None
    except Exception:
        return None


# ============================================================
# Agent循环
# ============================================================
def agent_loop(question, history, status_container, dev_mode=False):
    clean_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-(MAX_HISTORY_TURNS * 2):]
    ]

    scope_title = detect_scope_title(question)
    user_content = question
    if scope_title:
        status_container.write(f"🔒 已识别范围限定：仅检索《{scope_title}》（程序强制，不依赖模型判断）")
        user_content = (
            f"{question}\n\n"
            f"（系统提示：已将本轮检索范围程序化锁定为《{scope_title}》，search_corpus/"
            f"expand_chunk工具本轮只会返回该书内容，无需自行传入title参数，也无法获取"
            f"该书之外的片段。）"
        )
    messages = clean_history + [{"role": "user", "content": user_content}]

    tool_call_count = 0
    llm_round = 0
    all_retrieved_chunks = []
    seen_chunk_ids = set()

    # ---- A10：程序化检索计划（先计划后执行，结果以plan_N工具消息进入上下文）----
    plan = _make_retrieval_plan(question)
    if plan:
        status_container.write(f"🧭 已制定检索计划：{len(plan)} 步")
        if dev_mode:
            dev_record("检索计划（A10）", json.dumps(
                [{"purpose": p, "args": a} for a, p in plan],
                ensure_ascii=False, indent=2), is_json=True)
        plan_calls, plan_results = [], []
        for i, (args, purpose) in enumerate(plan):
            call_id = f"plan_{i}"
            plan_calls.append({
                "id": call_id, "type": "function",
                "function": {"name": "search_corpus", "arguments": json.dumps(args, ensure_ascii=False)},
            })
            tool_call_count += 1
            t0 = time.time()
            status_container.write(f"🧭 执行计划第{i+1}步：检索（{purpose or args['query'][:40]}）")
            result_str = execute_tool("search_corpus", args, scope_title=scope_title)
            result_data = json.loads(result_str)
            if dev_mode:
                dev_record(f"计划检索 · 第{i+1}步 · {purpose or args['query'][:40]}",
                           json.dumps({"输入": args, "输出": result_data}, ensure_ascii=False, indent=2),
                           is_json=True, elapsed=time.time() - t0)
            if isinstance(result_data, list):
                for item in result_data:
                    cid = item.get("chunk_id") if isinstance(item, dict) else None
                    if cid and cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        all_retrieved_chunks.append(item)
            plan_results.append({"role": "tool", "tool_call_id": call_id, "content": result_str})
        # thinking模式要求带tool_calls的assistant消息必须含reasoning_content字段（可空），
        # DeepSeek不接受content为null，用空字符串
        messages.append({"role": "assistant", "content": "", "reasoning_content": "",
                         "tool_calls": plan_calls})
        messages.extend(plan_results)

    while tool_call_count < MAX_TOOL_CALLS:
        llm_round += 1
        if dev_mode:
            msgs_brief = []
            for m in messages:
                brief = {"role": m["role"]}
                if m.get("content"):
                    brief["content"] = _clip(m["content"], DEV_CLIP_MSG)
                if m.get("tool_calls"):
                    brief["tool_calls"] = [
                        {"name": tc["function"]["name"],
                         "arguments": tc["function"]["arguments"]}
                        for tc in m["tool_calls"]
                    ]
                msgs_brief.append(brief)
            dev_record(f"LLM调用 第{llm_round}轮 · 输入", json.dumps(
                {"messages_count": len(messages), "messages": msgs_brief},
                ensure_ascii=False, indent=2), is_json=True)

        t0 = time.time()
        response = call_deepseek(
            messages=messages, system_prompt=SYSTEM_PROMPT, tools=TOOLS, temperature=0.3
        )
        if "error" in response:
            if dev_mode:
                dev_record(f"LLM调用 第{llm_round}轮 · 报错", response["error"])
            return f"⚠️ {response['error']}", all_retrieved_chunks

        choice = response["choices"][0]
        finish_reason = choice["finish_reason"]
        message = choice["message"]

        if dev_mode:
            dev_record(f"LLM调用 第{llm_round}轮 · 输出", json.dumps({
                "finish_reason": finish_reason,
                "content": _clip(message.get("content") or "", DEV_CLIP_MSG),
                "tool_calls": [
                    {"id": tc["id"], "name": tc["function"]["name"],
                     "arguments": tc["function"]["arguments"]}
                    for tc in (message.get("tool_calls") or [])
                ] or None,
            }, ensure_ascii=False, indent=2), is_json=True, elapsed=time.time() - t0)

        assistant_msg = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("reasoning_content"):
            # thinking模式要求：模型产生的带tool_calls消息必须把reasoning_content回传给API
            assistant_msg["reasoning_content"] = message["reasoning_content"]
        if message.get("tool_calls"):
            assistant_msg["tool_calls"] = message["tool_calls"]
        messages.append(assistant_msg)

        if finish_reason != "tool_calls" or not message.get("tool_calls"):
            return message.get("content", "（无回答）"), all_retrieved_chunks

        tool_results = []
        for tc in message["tool_calls"]:
            tool_name = tc["function"]["name"]
            tool_args = json.loads(tc["function"]["arguments"])
            tool_call_count += 1

            status_container.write(f"🔍 调用工具：**{tool_name}**（第{tool_call_count}次）")

            t0 = time.time()
            result_str = execute_tool(tool_name, tool_args, scope_title=scope_title)
            result_data = json.loads(result_str)

            if dev_mode:
                dev_record(f"工具执行 · {tool_name}（第{tool_call_count}次）", json.dumps(
                    {"输入": tool_args, "输出": result_data},
                    ensure_ascii=False, indent=2), is_json=True, elapsed=time.time() - t0)

            if tool_name in ("search_corpus", "expand_chunk") and isinstance(result_data, list):
                for item in result_data:
                    cid = item.get("chunk_id") if isinstance(item, dict) else None
                    if cid and cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        all_retrieved_chunks.append(item)

            tool_results.append({
                "role": "tool", "tool_call_id": tc["id"], "content": result_str
            })

        messages.extend(tool_results)

    if dev_mode:
        dev_record("循环终止 · 超过工具调用上限",
                   f"已连续调用 {tool_call_count} 次工具，达到 MAX_TOOL_CALLS={MAX_TOOL_CALLS}")
    return "⚠️ 工具调用次数超过上限，请缩短问题或降低复杂度。", all_retrieved_chunks


# ============================================================
# 长文本分析模式（三阶段台账式）
# ============================================================
LONG_CLAIM_MAX_TOOLS = 20   # 每个论点小循环的内置护栏（总体不设上限）

LONG_TEXT_SYSTEM_PROMPT = """你是奥匈帝国史研究助手的长文本核查员。你的任务：对长文本中的某一个论点做史料核查。

【核查方法论】
1. 先用 search_corpus 检索与本论点直接相关的史料（查询用英文效果更好），
   必要时换关键词、换角度补充检索
2. 【二手史料处理——最重要的规则】二手史学论著（如 Judson、Beller 等学者的著作）
   的论断不能直接当作最终论据：
   - 必须用 expand_chunk 展开其上下文，还原该学者的论证思路；
   - 识别该学者所引用的具体一手论据（文件、电报、官方记录、亲历者材料等）；
   - 再检索该一手论据本身，核实二手著作是否准确转述、论据是否真实存在。
3. 交叉核查：任务消息中的 cross_refs 标注了相关论点，检索时注意覆盖相关线索；
   已核查结论见任务消息中的台账摘要，可引用但不必重复检索。
4. 证据不足就如实标注，不要强行下结论。

【一手史料识别（重要：source_type 标签不可信）】
- 库内 source_type 标签是 ingest 时的粗略标注，存在错标（如官方战史
  《Österreich-Ungarns letzter Krieg》被标为 secondary）。primary 过滤只可作线索。
- 一手性判断要多通道交叉：
  a) 书名与内容形态：文件汇编、条约文本、电报原文、档案编号等；
  b) 作者身份与出版机构：外交部/总参谋部等官方出版物、当事人署名——
     可用 get_book_info 查看作者与出版机构；
  c) 用 expand_chunk 观察文本形态（电报编号、落款、公文格式、第一人称记录）。
- 官方战史、政府出版物、当事人回忆录、档案汇编即便被标为 secondary，
  按史源学应按一手/准一手对待，并在结论中说明判断依据。

【裁决提交】
核查充分后必须调用 record_verdict 提交结论：
- verdict：supported（有史料支持）/ contradicted（与史料矛盾）/
  partially_supported（部分成立部分不成立）/ insufficient（库内史料不足以判断）
- evidence_grade：primary_direct（一手史料直接支持或反驳）/
  secondary_with_primary（二手论证，已核其引用的一手论据）/
  secondary_only（仅有二手论断，未能核实其一手论据）/ unverified（无法核实）
- citations：支撑或反驳结论的引用文本（逐字使用片段的 citation 字段）
- chunk_ids：对应片段的 chunk_id
- reasoning：简要论证过程，包括二手著作的论证思路及其所引一手论据的核实情况"""

DECOMPOSE_PROMPT_TEMPLATE = """你是史学文本分析的任务分解器。请把下面的长文本拆解为可逐一核查的论点清单。

要求：
1. 每个论点应当是文本中明确提出的、可被史料证实或证伪的具体论断
   （事实判断、因果主张、数据引用、对某著作/学者观点的转述等）
2. verify_focus 写核查要点（要核实什么、特别要注意什么）
3. cross_refs 列出需要与哪些其他论点交叉核对（没有则填空数组）
4. 拆分粒度：信息密度高的文本约每200-400字一条，宁细勿粗；不要整段合并为一条
5. 严格输出JSON，不要输出任何JSON之外的文字：
{{"claims": [{{"id": 1, "claim_text": "论点原文或准确概括", "verify_focus": "核查要点", "cross_refs": []}}]}}

长文本：
{text}"""

REPORT_SYSTEM_PROMPT = """你是奥匈帝国历史研究专家。请基于下面的核查台账，为提交的长文本撰写一份分析报告。

默认报告结构（用户的"分析要求"如有说明，以其为准覆盖默认结构）：
1. 总体判断
2. 逐论点核查（按论点编号：支持/部分支持/矛盾/无法证实 + 引用 + 证据等级 + 置信度）
3. 二手论点溯源分析（学者的论证思路 → 其引用的一手论据 → 核实结果）
4. 修改建议

写作规范：
- 以转述为主，直接引用原文仅用于关键句；每处引用照抄片段的 citation 字段格式——
  二手著作与回忆录为 (作者, 年份[, p. 页码])，档案汇编类为「卷次, Nr. 编号」
  （如 ÖUA VIII, Nr. 10364 / MRP 3/8/2, Nr. 220）。不要编造页码，片段无页码时只写
  (作者, 年份)；档案类不要改写成 (作者, 年份, p. 页码)
- 严格区分：史料直接支持 / 可推断 / 史料未涉及（库内无法证实）
- 明确标注证据等级，二手论断与一手论据分开呈现
- 用中文回答，专有名词保留原文并附中文译名"""

RECORD_VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "record_verdict",
        "description": "完成当前论点的史料核查后提交裁决结论。调用此工具即结束本论点的核查。",
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "integer", "description": "论点编号"},
                "verdict": {
                    "type": "string",
                    "enum": ["supported", "contradicted", "partially_supported", "insufficient"],
                },
                "evidence_grade": {
                    "type": "string",
                    "enum": ["primary_direct", "secondary_with_primary", "secondary_only", "unverified"],
                },
                "citations": {
                    "type": "array", "items": {"type": "string"},
                    "description": "支撑/反驳结论的引用（逐字使用片段的citation字段）",
                },
                "chunk_ids": {
                    "type": "array", "items": {"type": "string"},
                    "description": "对应片段的chunk_id",
                },
                "reasoning": {
                    "type": "string",
                    "description": "简要论证过程（含二手著作论证思路与所引一手论据的核实情况）",
                },
            },
            "required": ["claim_id", "verdict", "evidence_grade", "reasoning"],
        },
    },
}

LONG_TEXT_TOOLS = TOOLS + [RECORD_VERDICT_TOOL]


def decompose_long_text(text):
    """阶段一：把长文本拆解为论点清单。返回[{id, claim_text, verify_focus, cross_refs}]或None"""
    prompt = DECOMPOSE_PROMPT_TEMPLATE.format(text=text)
    try:
        resp = call_deepseek([{"role": "user", "content": prompt}], temperature=0.2)
        if "error" in resp:
            return None
        raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        plan = json.loads(m.group(0))
        claims = plan.get("claims") or []
        out = []
        for c in claims:
            cid = c.get("id")
            ct = (c.get("claim_text") or "").strip()
            if cid is None or not ct:
                continue
            out.append({
                "id": int(cid),
                "claim_text": ct,
                "verify_focus": (c.get("verify_focus") or "").strip(),
                "cross_refs": [int(x) for x in (c.get("cross_refs") or []) if isinstance(x, (int, float))],
            })
        return out or None
    except Exception:
        return None


def _ledger_summary(ledger):
    if not ledger:
        return "（暂无已核查结论）"
    lines = []
    for v in ledger:
        cit = "；".join((v.get("citations") or [])[:3])
        lines.append(
            f"论点{v.get('id')}: {v.get('verdict')} | 证据等级 {v.get('evidence_grade')}"
            f" | 引用: {cit or '无'} | {_clip(v.get('reasoning') or '', 150)}"
        )
    return "\n".join(lines)


def build_claim_task(claim, all_claims, ledger):
    lines = [
        f"【当前任务】核查长文本中的第 {claim['id']} 号论点。",
        f"论点内容：{claim['claim_text'][:1000]}",
        f"核查要点：{claim.get('verify_focus') or '逐句核实其事实与论证'}",
        "",
        f"全文论点清单（共 {len(all_claims)} 条，仅供交叉核查参考）：",
    ]
    for c in all_claims:
        mark = "✓已核" if any(v.get("id") == c["id"] for v in ledger) else "○待核"
        lines.append(f"  {mark} {c['id']}. {_clip(c['claim_text'], 120)}")
    if claim.get("cross_refs"):
        lines.append(f"与本论点需交叉核对的论点编号：{claim['cross_refs']}")
    lines.append("")
    lines.append("已核查结论摘要：")
    lines.append(_ledger_summary(ledger))
    lines.append("")
    lines.append("核查完成后调用 record_verdict 提交结论。")
    return "\n".join(lines)


def verify_claim(claim, all_claims, ledger, status_container, dev_mode):
    """
    阶段二：单论点核查小循环。
    返回 (该论点检索到的chunks列表, verdict字典或None)。
    每论点最多 LONG_CLAIM_MAX_TOOLS 次工具调用（护栏）；总体无上限。
    """
    messages = [{"role": "user", "content": build_claim_task(claim, all_claims, ledger)}]
    chunks, seen_ids = [], set()
    tool_count = 0
    verdict = None

    while tool_count < LONG_CLAIM_MAX_TOOLS:
        t0 = time.time()
        resp = call_deepseek(
            messages=messages, system_prompt=LONG_TEXT_SYSTEM_PROMPT,
            tools=LONG_TEXT_TOOLS, temperature=0.3,
        )
        if "error" in resp:
            status_container.write(f"⚠️ 论点{claim['id']}核查出错：{resp['error']}")
            if dev_mode:
                dev_record(f"长文本 · 论点{claim['id']} · LLM报错", resp["error"])
            break
        msg = resp["choices"][0]["message"]
        assistant_msg = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("reasoning_content"):
            assistant_msg["reasoning_content"] = msg["reasoning_content"]
        if msg.get("tool_calls"):
            assistant_msg["tool_calls"] = msg["tool_calls"]
        messages.append(assistant_msg)

        if not msg.get("tool_calls"):
            break  # 模型未提交裁决直接结束

        results = []
        submitted = False
        for tc in msg["tool_calls"]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}

            if name == "record_verdict":
                try:
                    verdict = {
                        "id": int(args.get("claim_id") or claim["id"]),
                        "verdict": args.get("verdict") or "insufficient",
                        "evidence_grade": args.get("evidence_grade"),
                        "citations": [str(x) for x in (args.get("citations") or [])],
                        "chunk_ids": [str(x) for x in (args.get("chunk_ids") or [])],
                        "reasoning": str(args.get("reasoning") or ""),
                    }
                except Exception as e:
                    verdict = {"id": claim["id"], "verdict": "insufficient",
                               "evidence_grade": None, "citations": [], "chunk_ids": [],
                               "reasoning": f"裁决参数解析失败：{e}"}
                if dev_mode:
                    dev_record(f"长文本 · 论点{claim['id']} · 裁决", json.dumps(
                        verdict, ensure_ascii=False, indent=2), is_json=True)
                results.append({"role": "tool", "tool_call_id": tc["id"],
                                "content": json.dumps({"status": "recorded"}, ensure_ascii=False)})
                submitted = True
                break

            tool_count += 1
            status_container.write(
                f"🧭 论点{claim['id']} · 调用 {name}（本论点第{tool_count}次）")
            t_tool = time.time()
            # 长文本模式：无scope锁定、不使用侧边栏过滤（全库视野）
            result_str = execute_tool(name, args, scope_title=None, apply_ui_filters=False)
            result_data = json.loads(result_str)
            if dev_mode:
                dev_record(f"长文本 · 论点{claim['id']} · {name}",
                           json.dumps({"输入": args, "输出": result_data}, ensure_ascii=False, indent=2),
                           is_json=True, elapsed=time.time() - t_tool)
            if name in ("search_corpus", "expand_chunk") and isinstance(result_data, list):
                for item in result_data:
                    cid = item.get("chunk_id") if isinstance(item, dict) else None
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        chunks.append(item)
            results.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})

        messages.extend(results)
        if submitted:
            break

    return chunks, verdict


def build_report_messages(long_text, requirements, ledger):
    reqs = requirements or "按默认报告结构输出。"
    ledger_text = "\n".join(
        f"[论点{v.get('id')}] verdict={v.get('verdict')} | grade={v.get('evidence_grade')} | "
        f"citations={v.get('citations')} | chunk_ids={v.get('chunk_ids')} | "
        f"reasoning={v.get('reasoning')}"
        for v in ledger
    ) or "（无）"
    return [{
        "role": "user",
        "content": (
            f"【待分析长文本】\n{long_text}\n\n"
            f"【分析要求】\n{reqs}\n\n"
            f"【核查台账】\n{ledger_text}"
        ),
    }]


# ============================================================
# 引用校验（回答生成后自动执行，不是agent工具）
# ============================================================
def postprocess_answer(answer, retrieved_chunks, dev_mode=False):
    """
    回答生成后的统一后处理（不是agent工具，是流程里硬编码的一步）：
    1. 检查回答中的引用标注是否有对应检索片段支持，防止编造引文
    2. 从本轮检索到的所有候选片段中，筛出真正被直接引用/提及，或对回答有
       重大帮助的片段，用于下方展开面板展示——避免把几十个候选片段（包括
       检索到但最终没用上的）都堆给用户看
    3. 生成引用↔片段映射（A13），供回答下方"引用对照"面板展示
    返回 (处理后的回答文本, 筛选后的片段列表, 引用映射列表)
    """
    if not retrieved_chunks or not answer:
        return answer, [], []

    indexed = list(retrieved_chunks)
    pool_lines = "\n".join(
        f"{i}. chunk_id={c.get('chunk_id')} | citation={c.get('citation','')}"
        for i, c in enumerate(indexed)
    )
    if dev_mode:
        dev_record("引用校验 · 输入", json.dumps({
            "answer": _clip(answer, 3000),
            "candidate_chunks": [
                {"index": i, "chunk_id": c.get("chunk_id"), "citation": c.get("citation")}
                for i, c in enumerate(indexed)
            ],
        }, ensure_ascii=False, indent=2), is_json=True)
    check_messages = [{
        "role": "user",
        "content": (
            "以下是一段回答文本，以及本次对话中实际检索到的候选片段清单（编号 | chunk_id | citation）。\n"
            "请完成三件事，并严格以JSON格式返回，不要输出任何JSON之外的文字：\n"
            "1. used_indices：回答中直接引用、明确提及，或对回答的论证有重大帮助的片段编号列表"
            "（不包括检索到但回答里完全没用上的无关片段）\n"
            "2. citation_issues：检查回答里每处引用标注是否都能在候选片段清单中找到对应依据。\n"
            "   注意引用有两类合法形制，都要认：(a)「(作者, 年份, p. 页码)」或「(作者, 年份)」；"
            "(b) 档案汇编类的「卷次, Nr. 编号」（如 ÖUA VIII, Nr. 10364 / MRP 3/8/2, Nr. 220）。\n"
            "   只有当清单中完全没有该引用所指的作者/年份/页码组合、或完全没有该卷次与文件编号时，"
            "才算编造；简要说明是哪几处有问题。如果都有依据，此字段填null\n"
            "3. citation_map：把回答中每一处引用标注映射到其对应的候选片段编号"
            "（citation_text逐字复制自回答，无法定位到具体片段的不要列进来）\n\n"
            '返回格式：{"used_indices": [0, 2, 5], "citation_issues": null, '
            '"citation_map": [{"citation_text": "(Beller, 1989, p. 18)", "chunk_index": 3}, '
            '{"citation_text": "ÖUA VIII, Nr. 10364", "chunk_index": 7}]}\n\n'
            f"【回答文本】\n{answer}\n\n【候选片段清单】\n{pool_lines}"
        ),
    }]
    resp = _check_call(check_messages, temperature=0)
    if "error" in resp:
        return answer, retrieved_chunks, []  # 后处理本身失败时，退回显示全部候选，不影响正常回答

    raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    if dev_mode:
        dev_record("引用校验 · 校验模型原始输出", _clip(raw, 2000))
    try:
        parsed = json.loads(raw)
        used_indices = parsed.get("used_indices", [])
        cited_chunks = []
        seen = set()
        for i in used_indices:
            if not (isinstance(i, int) and 0 <= i < len(indexed)):
                continue
            c = indexed[i]
            cid = c.get("chunk_id")
            if cid in seen:
                continue
            seen.add(cid)
            cited_chunks.append(c)
        issues = parsed.get("citation_issues")
        # A13：引用↔片段映射，附带展示所需的书目信息
        citation_map = []
        for cm in parsed.get("citation_map") or []:
            if not isinstance(cm, dict):
                continue
            idx = cm.get("chunk_index")
            text = (cm.get("citation_text") or "").strip()
            if isinstance(idx, int) and 0 <= idx < len(indexed) and text:
                c = indexed[idx]
                citation_map.append({
                    "citation_text": text,
                    "chunk_id": c.get("chunk_id"),
                    "source": c.get("source"),
                    "chapter_title": c.get("chapter_title"),
                    "citation": c.get("citation"),
                })
        if dev_mode:
            dev_record("引用校验 · 解析结果", json.dumps(
                {"used_indices": used_indices, "citation_issues": issues,
                 "citation_map_count": len(citation_map)},
                ensure_ascii=False, indent=2), is_json=True)
    except Exception:
        if dev_mode:
            dev_record("引用校验 · 解析失败", "返回内容不是合法JSON，已回退为显示全部候选片段")
        # 解析失败时保守处理：不筛选（显示全部候选），也不追加校验提示
        return answer, retrieved_chunks, []

    if issues:
        answer += f"\n\n---\n⚠️ **引用自查提示**：{issues}"

    # 极端情况下模型可能一个都没选中（比如判断过严），此时退回显示全部候选，
    # 避免用户看到"检索了但什么都不展示"的空面板
    return answer, cited_chunks if cited_chunks else retrieved_chunks, citation_map


# ============================================================
# 展示辅助
# ============================================================
def _resolve_chunk_index(c):
    idx = c.get("chunk_index")
    if isinstance(idx, int):
        return idx
    # 兜底：chunk_index字段缺失时，从chunk_id（格式 title::chunk_index）里解析
    cid = c.get("chunk_id") or ""
    if "::" in cid:
        try:
            return int(cid.rsplit("::", 1)[-1])
        except ValueError:
            return None
    return None


def merge_adjacent_chunks(chunks):
    """
    展示前的合并与排序：
    1. 同一本书内chunk_index连续（相差<=1）的片段大概率是expand_chunk产出的相邻窗口，
       内容因ingest时加的overlap而大段重叠——合并成一个展示单元，页码显示为范围
       （如 p. 42-45），而不是拆成多个几乎同文的框
    2. 最终按（书名, 起始chunk_index）排序，让片段按原书顺序呈现，方便定位
    """
    valid = [c for c in chunks if isinstance(c, dict)]

    grouped = {}
    for c in valid:
        grouped.setdefault(c.get("title"), []).append(c)

    merged = []
    for title, group in grouped.items():
        group.sort(key=lambda c: _resolve_chunk_index(c) or 0)
        current = None
        for c in group:
            idx = _resolve_chunk_index(c)
            if (
                current is not None
                and isinstance(idx, int)
                and isinstance(current["_last_idx"], int)
                and idx - current["_last_idx"] <= 1
                # 档案汇编类：不同文件号之间即使 chunk_index 相邻也不得合并，
                # 否则会把两份不同文件拼进同一个展示面板——归属错误且无法事后修正。
                and c.get("doc_number") == current.get("doc_number")
            ):
                current["texts"].append(c.get("text", ""))
                current["pages"].append(c.get("page_num"))
                current["chunk_ids"].append(c.get("chunk_id"))
                current["_last_idx"] = idx
            else:
                if current:
                    merged.append(current)
                current = {
                    "title": title,
                    "author": c.get("author"),
                    "year": c.get("year"),
                    "source": c.get("source"),
                    "chapter_title": c.get("chapter_title"),
                    "source_type": c.get("source_type"),
                    "region": c.get("region"),
                    "doc_number": c.get("doc_number"),
                    "doc_date": c.get("doc_date"),
                    "doc_section": c.get("doc_section"),
                    "texts": [c.get("text", "")],
                    "pages": [c.get("page_num")],
                    "chunk_ids": [c.get("chunk_id")],
                    "_first_idx": idx if isinstance(idx, int) else 0,
                    "_last_idx": idx,
                }
        if current:
            merged.append(current)

    output = []
    for m in merged:
        pages = [p for p in m["pages"] if isinstance(p, int) and p != -1]
        if m.get("doc_number"):
            # 档案汇编类：输出「卷次, Nr. 编号」，与 corpus_lib 的引用规范一致
            citation = format_citation_tag({
                "title": m["title"],
                "doc_number": m.get("doc_number"),
                "doc_section": m.get("doc_section"),
            }, m["texts"][0])
        elif pages:
            page_str = f"p. {min(pages)}" if min(pages) == max(pages) else f"p. {min(pages)}-{max(pages)}"
            citation = f"{m.get('author') or '未知作者'}, {m.get('year') or '未知年份'}, {page_str}"
        else:
            citation = f"{m.get('author') or '未知作者'}, {m.get('year') or '未知年份'}"
        output.append({
            "chunk_id": m["chunk_ids"][0],
            "all_chunk_ids": m["chunk_ids"],
            "title": m["title"],
            "source": m["source"],
            "citation": citation,
            "chapter_title": m.get("chapter_title"),
            "source_type": m.get("source_type"),
            "region": m.get("region"),
            "doc_number": m.get("doc_number"),
            "doc_date": m.get("doc_date"),
            "doc_section": m.get("doc_section"),
            "text": "\n\n···\n\n".join(m["texts"]),
            "_sort_key": (m["title"] or "", m["_first_idx"]),
        })

    output.sort(key=lambda c: c.pop("_sort_key"))
    return output


def render_chunk_expander(chunks):
    with st.expander(f"查看检索片段（共{len(chunks)}条）"):
        # 并行预修正本消息内所有未缓存的展示单元（flash，失败回退原文），
        # 避免逐片段串行等待；命中缓存时零开销
        units = [c for c in chunks if isinstance(c, dict)]
        if units:
            with st.spinner("🪄 正在修正片段排版与拼写（仅展示，检索与引用仍用原文）..."):
                fixed_n = correct_units(units, max_workers=6)
            if fixed_n:
                st.caption(f"🪄 本次新修正了 {fixed_n} 个片段的排版（结果已缓存，后续即时显示）")
        for i, chunk in enumerate(units):
            chapter = f" · 《{chunk['chapter_title']}》章节" if chunk.get("chapter_title") else ""
            st.markdown(f"##### 出处：《{chunk.get('source', '未知书目')}》")
            st.markdown(
                f"{chunk.get('citation','未知来源')}{chapter}"
                f" · {chunk.get('source_type','') or ''} · "
                f"{'/'.join(chunk.get('region') or []) if isinstance(chunk.get('region'), list) else chunk.get('region','')}"
            )
            st.caption("来源信息提取自 bookdata.json")
            raw_text = chunk.get("text", "")
            display_text = get_corrected_text(chunk)
            st.text(display_text)
            if display_text != raw_text:
                st.caption("🪄 文本已自动修正排版与拼写（仅影响展示，检索与引用仍用原文）")
            exclude_ids = chunk.get("all_chunk_ids") or [chunk.get("chunk_id")]
            btn_label = "🚫 排除此片段" if len(exclude_ids) == 1 else f"🚫 排除此片段（共{len(exclude_ids)}个子片段）"
            if st.button(btn_label, key=f"exclude_{chunk.get('chunk_id')}_{i}"):
                tool_exclude_chunks(exclude_ids, reason="用户手动排除")
                st.rerun()
            st.markdown("---")


# ============================================================
# 会话持久化（A16）/ 反馈（A26）/ 导出（A14）
# ============================================================
def _sessions_index_path():
    return os.path.join(SESSIONS_DIR, "index.json")


def load_sessions_index():
    try:
        with open(_sessions_index_path(), encoding="utf-8") as f:
            idx = json.load(f)
        if isinstance(idx, dict) and isinstance(idx.get("sessions"), list):
            return idx
    except Exception:
        pass
    return {"sessions": []}


def save_sessions_index(idx):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(_sessions_index_path(), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _session_path(sid):
    return os.path.join(SESSIONS_DIR, f"{sid}.jsonl")


def compact_sources(sources):
    """展示单元去掉正文，只保留chunk_id等元信息（A16：正文渲染时按id从库中还原）"""
    return [{k: v for k, v in (s or {}).items() if k not in ("text", "_sort_key")}
            for s in sources]


def save_session(sid, messages):
    """把消息列表原子写入会话文件（sources不存全文，避免文件膨胀）"""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    tmp = _session_path(sid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for m in messages:
            rec = {
                "role": m.get("role"),
                "content": m.get("content") or "",
                "sources": compact_sources(m.get("sources") or []),
                "dev_log": m.get("dev_log") or [],
                "citation_map": m.get("citation_map") or [],
                "long_text": m.get("long_text") or "",
                "long_reqs": m.get("long_reqs") or "",
                "ts": m.get("ts") or "",
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, _session_path(sid))


def load_session(sid):
    out = []
    try:
        with open(_session_path(sid), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:
        out = []
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_chunk_texts(chunk_ids):
    fetched = get_chunks_by_ids(list(chunk_ids))
    return {cid: c.get("text", "") for cid, c in fetched.items()}


def hydrate_sources(entries):
    """按chunk_id从库里还原展示单元的正文（A16：历史消息的sources不存全文）"""
    out = []
    for e in entries or []:
        ids = e.get("all_chunk_ids") or ([e.get("chunk_id")] if e.get("chunk_id") else [])
        texts = _fetch_chunk_texts(tuple(ids))
        unit = {k: v for k, v in e.items() if k not in ("text", "_sort_key")}
        unit["text"] = "\n\n···\n\n".join(
            texts.get(cid, f"（片段 {cid} 已不在库中）") for cid in ids
        )
        out.append(unit)
    return out


def _new_session_id():
    return time.strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(4).hex()


def _handle_session_actions(new_clicked, delete_clicked, delete_confirmed, selected_label):
    """处理会话的新建/切换/删除；返回True表示已触发rerun。"""
    idx = load_sessions_index()
    sessions = idx.get("sessions", [])
    cur = st.session_state.get("current_session")

    if new_clicked:
        sid = _new_session_id()
        save_session(sid, [])
        sessions.append({"id": sid, "name": "新会话",
                         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_sessions_index(idx)
        st.session_state.current_session = sid
        st.session_state.loaded_session = sid
        st.session_state.messages = []
        st.session_state.last_sources = None
        st.session_state.excluded_chunk_ids = set()
        st.session_state.dev_log = []
        st.rerun()
        return True

    if delete_clicked and delete_confirmed and sessions:
        sid = cur
        try:
            os.remove(_session_path(sid))
        except Exception:
            pass
        sessions[:] = [s for s in sessions if s.get("id") != sid]
        if not sessions:
            sid2 = _new_session_id()
            save_session(sid2, [])
            sessions.append({"id": sid2, "name": "新会话",
                             "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_sessions_index(idx)
        st.session_state.current_session = sessions[0]["id"]
        st.session_state.loaded_session = sessions[0]["id"]
        st.session_state.messages = []
        st.session_state.last_sources = None
        st.session_state.excluded_chunk_ids = set()
        st.session_state.dev_log = []
        st.rerun()
        return True

    # 切换会话：selectbox标签对应的id与当前不同
    sel_id = None
    for s in sessions:
        label = f"{s.get('name','新会话')} · {s.get('updated','')[:10]}"
        if label == selected_label:
            sel_id = s.get("id")
            break
    if sel_id and cur and sel_id != cur:
        save_session(cur, st.session_state.messages)
        st.session_state.current_session = sel_id
        st.session_state.loaded_session = sel_id
        st.session_state.messages = load_session(sel_id)
        st.session_state.last_sources = None
        st.session_state.excluded_chunk_ids = set()
        st.session_state.dev_log = []
        st.rerun()
        return True
    return False


def _touch_session(sid, messages):
    """回答生成后：保存会话并更新索引的name（首条问题）与updated"""
    idx = load_sessions_index()
    updated = time.strftime("%Y-%m-%d %H:%M:%S")
    name = "新会话"
    for m in messages:
        if m.get("role") == "user" and (m.get("content") or "").strip():
            name = m["content"].strip().replace("\n", " ")[:40]
            break
    found = False
    for s in idx.get("sessions", []):
        if s.get("id") == sid:
            s["name"] = name
            s["updated"] = updated
            found = True
            break
    if not found:
        idx.setdefault("sessions", []).append({"id": sid, "name": name,
                                               "created": updated, "updated": updated})
    save_sessions_index(idx)
    save_session(sid, messages)


def _append_feedback(msg_index, rating):
    """把点赞/点踩写入 feedback.jsonl（A26）"""
    try:
        msgs = st.session_state.messages
        msg = msgs[msg_index] if 0 <= msg_index < len(msgs) else {}
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": st.session_state.get("current_session"),
            "msg_index": msg_index,
            "rating": rating,
            "role": msg.get("role"),
            "content_snippet": (msg.get("content") or "")[:200],
        }
        with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _on_feedback(value, idx):
    _append_feedback(idx, value)


def build_export_md(question_text, message):
    """组装Markdown导出内容（A14）：问题 + 回答 + 引用片段（按id从库还原）+ 元信息"""
    lines = ["# 奥匈帝国史研究助手 · 对话导出", ""]
    lines.append(f"**问题**：{question_text}" if question_text else "**问题**：（未记录）")
    lines.append("")
    lines.append("## 回答")
    lines.append("")
    lines.append(message.get("content", ""))
    sources = hydrate_sources(message.get("sources") or [])
    if sources:
        lines.append("")
        lines.append("## 引用片段")
        lines.append("")
        for i, c in enumerate(sources, 1):
            chapter = f" · 《{c.get('chapter_title')}》" if c.get("chapter_title") else ""
            lines.append(f"### [{i}] 《{c.get('source', '未知书目')}》{chapter}")
            lines.append(f"- 引用：{c.get('citation', '未知')}")
            lines.append(f"- chunk_id：{c.get('chunk_id')}")
            lines.append("")
            lines.append(get_corrected_text(c))
            lines.append("")
    return "\n".join(lines)


# ============================================================
# 初始化
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_sources" not in st.session_state:
    st.session_state.last_sources = None
if "excluded_chunk_ids" not in st.session_state:
    st.session_state.excluded_chunk_ids = set()
if "dev_log" not in st.session_state:
    st.session_state.dev_log = []
if "current_session" not in st.session_state:
    st.session_state.current_session = None
if "loaded_session" not in st.session_state:
    st.session_state.loaded_session = None
if "dev_mode_on" not in st.session_state:
    st.session_state.dev_mode_on = False
if "ui_filters" not in st.session_state:
    st.session_state.ui_filters = {}
if "long_ledger" not in st.session_state:
    st.session_state.long_ledger = []


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.header("设置")
    deep_mode = st.toggle("深度分析模式", value=False,
                          help="开启后模型自主决定检索策略和次数，响应更慢但分析更全面")
    long_text_mode = st.toggle("长文本分析模式", value=False,
                               help="输入长文本+分析要求，三阶段台账式逐论点史料核查（耗时与费用较高）")
    dev_mode = st.toggle("开发者模式", value=False,
                         help="显示Agent执行轨迹：每一步的模型输入/输出、工具调用参数与返回结果")
    st.session_state["dev_mode_on"] = dev_mode
    if st.button("清空对话"):
        st.session_state.messages = []
        st.session_state.excluded_chunk_ids = set()
        st.session_state.dev_log = []
        sid = st.session_state.get("current_session")
        if sid:
            save_session(sid, [])
        st.rerun()

    st.markdown("---")
    st.header("检索过滤")
    st.caption("普通模式直接生效；深度模式会覆盖模型传的同类参数。")
    ui_source_type = st.selectbox("史料类型", ["不限"] + SOURCE_TYPE_CANDIDATES, key="ui_source_type")
    ui_stance = st.selectbox("史学立场", ["不限"] + STANCE_CANDIDATES, key="ui_stance")
    ui_lang = st.selectbox("语言", ["不限", "英文", "中文", "德文", "匈牙利文", "波兰文", "混合"], key="ui_lang")
    ui_subfields = st.multiselect("学科视角", SUBFIELD_CANDIDATES, key="ui_subfields")
    ui_regions = st.multiselect("地区", REGION_CANDIDATES, key="ui_regions")
    st.session_state["ui_filters"] = {
        "source_type": ui_source_type if ui_source_type != "不限" else None,
        "stance": ui_stance if ui_stance != "不限" else None,
        "lang": ui_lang if ui_lang != "不限" else None,
        "subfield": ui_subfields or None,
        "region": ui_regions or None,
    }
    if st.button("重置过滤"):
        for k in ("ui_source_type", "ui_stance", "ui_lang"):
            st.session_state[k] = "不限"
        for k in ("ui_subfields", "ui_regions"):
            st.session_state[k] = []
        st.rerun()

    st.markdown("---")
    st.header("会话")
    sidx = load_sessions_index()
    sessions = sorted(sidx.get("sessions", []), key=lambda s: s.get("updated", ""), reverse=True)
    if not sessions:
        sid0 = _new_session_id()
        save_session(sid0, [])
        sessions = [{"id": sid0, "name": "新会话",
                     "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "updated": time.strftime("%Y-%m-%d %H:%M:%S")}]
        save_sessions_index({"sessions": sessions})
    cur_sid = st.session_state.get("current_session")
    if not cur_sid or not any(s.get("id") == cur_sid for s in sessions):
        cur_sid = sessions[0]["id"]
        st.session_state.current_session = cur_sid
    if st.session_state.get("loaded_session") != cur_sid:
        st.session_state.messages = load_session(cur_sid)
        st.session_state.loaded_session = cur_sid
    session_labels = [f"{s.get('name','新会话')} · {s.get('updated','')[:10]}" for s in sessions]
    sel_session_label = st.selectbox("会话", session_labels, key="ui_session_sel")
    sc1, sc2 = st.columns(2)
    new_session_btn = sc1.button("➕ 新建")
    delete_confirmed = st.checkbox("确认删除当前会话", key="ui_session_del_confirm")
    delete_btn = sc2.button("🗑️ 删除", disabled=not delete_confirmed)

    st.markdown("---")
    st.caption("史料库状态")
    try:
        col = get_collection()
        st.success(f"已载入 {col.count()} 个片段")
    except Exception:
        st.error("数据库连接失败")
    excluded_n = len(st.session_state.get("excluded_chunk_ids", set()))
    if excluded_n:
        st.caption(f"本次对话已排除 {excluded_n} 个片段")
    try:
        with open(FEEDBACK_PATH, encoding="utf-8") as f:
            fb_n = sum(1 for _ in f)
    except Exception:
        fb_n = 0
    if fb_n:
        st.caption(f"已收集用户反馈 {fb_n} 条")

_handle_session_actions(new_session_btn, delete_btn, delete_confirmed, sel_session_label)


# ============================================================
# 显示历史对话
# ============================================================
for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("long_text"):
            with st.expander("查看提交的长文本"):
                st.text(message["long_text"])
        if message.get("sources"):
            render_chunk_expander(hydrate_sources(message["sources"]))
        if message.get("citation_map"):
            with st.expander(f"🔗 引用对照（{len(message['citation_map'])} 处）"):
                for cm in message["citation_map"]:
                    chapter = f" · 《{cm['chapter_title']}》" if cm.get("chapter_title") else ""
                    st.markdown(
                        f"**{cm.get('citation_text','')}** → "
                        f"《{cm.get('source','未知书目')}》{chapter} · `{cm.get('chunk_id')}`"
                    )
        if dev_mode and message.get("dev_log"):
            render_dev_log(message["dev_log"])
        if message["role"] == "assistant":
            q_text = ""
            if i >= 1 and st.session_state.messages[i - 1].get("role") == "user":
                q_text = st.session_state.messages[i - 1].get("content", "")
            md = build_export_md(q_text, message)
            st.download_button(
                "⬇️ 导出 Markdown", data=md, file_name=f"habrag_{i}.md",
                mime="text/markdown", key=f"export_{i}",
            )
            st.feedback("thumbs", key=f"feedback_{i}", on_change=_on_feedback, args=(i,))


# ============================================================
# 输入框
# ============================================================
with st.form("question_form", clear_on_submit=True):
    if long_text_mode:
        long_text_input = st.text_area("待分析长文本", height=340,
                                       help="粘贴需要详细分析/核查的长文本（论文、观点陈述等）")
        long_reqs_input = st.text_area("分析要求/备注（回答模式、注意事项、任何补充指令）", height=130)
        submitted = st.form_submit_button("开始分析")
        continue_chat = False
        question = ""
    else:
        question = st.text_input("输入你的问题...")
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("发送")
        with col2:
            continue_chat = st.form_submit_button("继续对话（不重新检索）")
        long_text_input = ""
        long_reqs_input = ""

if long_text_mode and submitted and long_text_input.strip():
    st.session_state.dev_log = []
    long_text = long_text_input.strip()
    long_reqs = long_reqs_input.strip()

    with st.chat_message("user"):
        st.markdown(f"**📜 长文本分析请求**（{len(long_text)} 字）")
        with st.expander("查看提交的长文本"):
            st.text(long_text)
        st.markdown("**分析要求/备注**：\n\n" + (long_reqs or "（未填写，按默认结构输出）"))

    with st.chat_message("assistant"):
        est_claims = max(2, min(80, round(len(long_text) / 400)))
        est_min = round(est_claims * 2.5)
        st.info(
            f"预计拆分为约 {est_claims} 个论点逐一核查（实测每论点约 2-3 分钟），"
            f"总计约 {est_min} 分钟；费用约 ¥5-15（非高峰时段）。"
            f"分析进行中请勿刷新页面（进度不落盘）。"
        )

        status = st.empty()

        # ---- 阶段一：分解 ----
        status.write("🧭 阶段一：分解长文本为可核查论点...")
        t0 = time.time()
        claims = decompose_long_text(long_text)
        if dev_mode:
            dev_record("长文本 · 阶段一 · 分解", json.dumps(
                claims or {}, ensure_ascii=False, indent=2), is_json=True,
                elapsed=time.time() - t0)
        if not claims:
            status.write("⚠️ 分解失败，降级为把全文当作单一论点核查")
            claims = [{"id": 1, "claim_text": long_text[:1500],
                       "verify_focus": "全文核心事实与论证", "cross_refs": []}]

        # ---- 阶段二：逐论点核查（台账，session内存） ----
        ledger = []
        st.session_state["long_ledger"] = ledger
        all_retrieved = []
        total = len(claims)
        for ci, claim in enumerate(claims):
            status.write(f"🧭 阶段二：核查论点 {ci + 1}/{total} · 「{_clip(claim['claim_text'], 60)}」")
            t0 = time.time()
            c_chunks, verdict = verify_claim(claim, claims, ledger, status, dev_mode)
            all_retrieved.extend(c_chunks)
            if verdict is None:
                verdict = {"id": claim["id"], "verdict": "insufficient",
                           "evidence_grade": None, "citations": [], "chunk_ids": [],
                           "reasoning": "模型未提交裁决"}
            ledger.append(verdict)
            if dev_mode:
                dev_record(f"长文本 · 论点{claim['id']} · 核查完成",
                           f"耗时 {time.time() - t0:.1f}s，累计检索片段 {len(all_retrieved)}")
        st.session_state["long_ledger"] = ledger

        # ---- 阶段三：综合报告（流式） ----
        status.write("🧭 阶段三：综合报告生成中...")
        report_messages = build_report_messages(long_text, long_reqs, ledger)
        if dev_mode:
            dev_record("长文本 · 阶段三 · 报告输入", _clip(
                report_messages[0]["content"], 3000))
        t0 = time.time()
        try:
            answer = st.write_stream(call_deepseek_stream(report_messages, REPORT_SYSTEM_PROMPT))
        except Exception as e:
            st.error(f"报告生成失败：{e}")
            answer = "⚠️ 报告生成失败，请重新提交。"
        if dev_mode:
            dev_record("长文本 · 阶段三 · 报告输出", _clip(answer, 3000),
                       elapsed=time.time() - t0)
        status.empty()

        # ---- 后处理：候选池收敛（台账引用片段优先 + 最近检索片段，上限150） ----
        cited_ids = {cid for v in ledger for cid in (v.get("chunk_ids") or [])}
        pool, pool_ids = [], set()
        for c in all_retrieved:
            cid = c.get("chunk_id")
            if cid in cited_ids and cid not in pool_ids:
                pool.append(c)
                pool_ids.add(cid)
        for c in all_retrieved:
            cid = c.get("chunk_id")
            if cid not in pool_ids:
                pool.append(c)
                pool_ids.add(cid)
            if len(pool) >= 150:
                break

        t0 = time.time()
        with st.spinner("正在核对引用..."):
            answer, display_chunks, citation_map = postprocess_answer(answer, pool, dev_mode=dev_mode)
        if dev_mode:
            dev_record("引用校验 · 总耗时", f"{time.time() - t0:.2f}s")

        display_chunks = merge_adjacent_chunks(display_chunks)[:30]

        st.markdown(answer)
        if display_chunks:
            render_chunk_expander(display_chunks)
        if citation_map:
            with st.expander(f"🔗 引用对照（{len(citation_map)} 处）"):
                for cm in citation_map:
                    chapter = f" · 《{cm['chapter_title']}》" if cm.get("chapter_title") else ""
                    st.markdown(
                        f"**{cm.get('citation_text','')}** → "
                        f"《{cm.get('source','未知书目')}》{chapter} · `{cm.get('chunk_id')}`"
                    )
        if dev_mode:
            render_dev_log()

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.messages.append({
        "role": "user",
        "content": f"**📜 长文本分析请求**（{len(long_text)} 字）\n\n**分析要求/备注**：{long_reqs or '（未填写）'}",
        "long_text": long_text,
        "long_reqs": long_reqs,
        "ts": ts,
    })
    st.session_state.messages.append({
        "role": "assistant", "content": answer,
        "sources": compact_sources(display_chunks),
        "dev_log": list(st.session_state.dev_log) if dev_mode else [],
        "citation_map": citation_map,
        "ts": ts,
    })
    st.session_state.last_sources = pool
    sid = st.session_state.get("current_session")
    if sid:
        _touch_session(sid, st.session_state.messages)
    st.rerun()

elif (submitted or continue_chat) and question:
    st.session_state.dev_log = []
    use_last_sources = continue_chat and st.session_state.last_sources is not None
    scope_title = detect_scope_title(question)
    if dev_mode:
        dev_record("范围识别 detect_scope_title", json.dumps(
            {"输入": {"question": question}, "输出": {"scope_title": scope_title}},
            ensure_ascii=False, indent=2), is_json=True)
        dev_record("系统提示词 SYSTEM_PROMPT", SYSTEM_PROMPT)

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        if scope_title:
            st.caption(f"🔒 已识别范围限定：仅使用《{scope_title}》的内容")

        if use_last_sources:
            retrieved_chunks = st.session_state.last_sources
            if scope_title:
                # 硬过滤：不管上一轮检索到了什么，这一轮明确限定范围后，
                # 范围外的内容物理上不进入context，不依赖模型自觉忽略
                retrieved_chunks = [c for c in retrieved_chunks if c.get("title") == scope_title]
            context = "\n\n".join([
                f"[{c.get('citation','?')}]\n{c.get('text','')}"
                for c in retrieved_chunks
            ])
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[-(MAX_HISTORY_TURNS * 2):]
            ]
            history.append({
                "role": "user",
                "content": f"（继续基于上次检索到的史料片段讨论）\n\n史料片段：\n{context}\n\n问题：{question}",
            })
            if dev_mode:
                dev_record("生成 · 流式 call_deepseek（继续对话，不重新检索）", json.dumps({
                    "history_turns": len(history) - 1,
                    "context_chunks": len(retrieved_chunks),
                    "last_user_content": _clip(history[-1]["content"], 3000),
                }, ensure_ascii=False, indent=2), is_json=True)
            t0 = time.time()
            try:
                answer = st.write_stream(call_deepseek_stream(history, SYSTEM_PROMPT))
            except Exception as e:
                st.error(f"生成失败：{e}")
                answer = "⚠️ 生成失败，请重新发送问题。"
            if dev_mode:
                dev_record("生成 · 模型输出", _clip(answer, 3000), elapsed=time.time() - t0)

        elif deep_mode:
            status = st.empty()
            status.write("🤔 正在分析问题...")
            answer, retrieved_chunks = agent_loop(question, st.session_state.messages, status, dev_mode=dev_mode)
            status.empty()

        else:
            t0 = time.time()
            try:
                with st.spinner("正在检索史料..."):
                    # scope_title非None时直接锁定title参数，range外内容压根不会被检索出来
                    # ui_filters()为侧边栏过滤条件（A11）
                    retrieved_chunks = tool_search_corpus(
                        query=question, title=scope_title, n_results=15, **ui_filters()
                    )
            except Exception as e:
                st.error(f"检索失败：{e}")
                retrieved_chunks = []
            if dev_mode:
                dev_record("检索 · search_corpus（A7混合+A8精排+A9改写）", json.dumps({
                    "输入": {"query": question, "title": scope_title, "n_results": 15,
                             "ui_filters": ui_filters()},
                    "输出": {
                        "retrieved_chunks": len(retrieved_chunks),
                        "chunks": [{"chunk_id": c.get("chunk_id"), "citation": c.get("citation")}
                                   for c in retrieved_chunks],
                    },
                }, ensure_ascii=False, indent=2), is_json=True, elapsed=time.time() - t0)

            context = "\n\n".join([
                f"[{c.get('citation','?')}]\n{c.get('text','')}"
                for c in retrieved_chunks
            ])
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[-(MAX_HISTORY_TURNS * 2):]
            ]
            history.append({
                "role": "user",
                "content": f"史料片段：\n{context}\n\n问题：{question}",
            })
            if dev_mode:
                dev_record("生成 · 流式 call_deepseek（单次检索模式）", json.dumps({
                    "history_turns": len(history),
                    "context_chunks": len(retrieved_chunks),
                    "last_user_content": _clip(history[-1]["content"], 3000),
                }, ensure_ascii=False, indent=2), is_json=True)
            t0 = time.time()
            try:
                answer = st.write_stream(call_deepseek_stream(history, SYSTEM_PROMPT))
            except Exception as e:
                st.error(f"生成失败：{e}")
                answer = "⚠️ 生成失败，请重新发送问题。"
            if dev_mode:
                dev_record("生成 · 模型输出", _clip(answer, 3000), elapsed=time.time() - t0)

        # 统一后处理：校验引用 + 筛出真正被引用/有重大帮助的片段 + 引用映射（A13）
        # （retrieved_chunks是本轮检索到的全部候选，display_chunks是筛选后要展示的子集）
        t0 = time.time()
        with st.spinner("正在核对引用..."):
            answer, display_chunks, citation_map = postprocess_answer(answer, retrieved_chunks, dev_mode=dev_mode)
        if dev_mode:
            dev_record("引用校验 · 总耗时", f"{time.time() - t0:.2f}s")

        # 范围锁定时的最后一道防线：即便前面某个环节意外漏了范围外内容进来
        # （理论上不会，但展示层再兜底一次，不给"检索到了但不该出现"留任何缝隙）
        if scope_title:
            display_chunks = [c for c in display_chunks if c.get("title") == scope_title]

        # 合并同书相邻片段 + 按书名/页码排序，避免expand_chunk产出的重叠窗口
        # 拆成多条几乎同文的展示框，也方便按页码顺序定位
        display_chunks = merge_adjacent_chunks(display_chunks)

        st.markdown(answer)
        if display_chunks:
            render_chunk_expander(display_chunks)
        if citation_map:
            with st.expander(f"🔗 引用对照（{len(citation_map)} 处）"):
                for cm in citation_map:
                    chapter = f" · 《{cm['chapter_title']}》" if cm.get("chapter_title") else ""
                    st.markdown(
                        f"**{cm.get('citation_text','')}** → "
                        f"《{cm.get('source','未知书目')}》{chapter} · `{cm.get('chunk_id')}`"
                    )
        if dev_mode:
            render_dev_log()

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.messages.append({"role": "user", "content": question, "ts": ts})
    st.session_state.messages.append({
        "role": "assistant", "content": answer,
        # A16：sources只存chunk_id等元信息，正文渲染时按id从库还原
        "sources": compact_sources(display_chunks),
        "dev_log": list(st.session_state.dev_log) if dev_mode else [],
        "citation_map": citation_map,
        "ts": ts,
    })
    # last_sources保留本轮完整候选池（不是筛选后的子集），供"继续对话"模式使用，
    # 避免连续对话时可用素材越用越少
    st.session_state.last_sources = retrieved_chunks
    sid = st.session_state.get("current_session")
    if sid:
        _touch_session(sid, st.session_state.messages)
    st.rerun()