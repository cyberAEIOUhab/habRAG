"""
corpus_lib.py —— 语料库共享数据层（本次新增，不改动 app.py）

背景：app.py 自带一套检索/富化逻辑，但直接 import app.py 会连带执行其 Streamlit
界面代码，不适合被脚本与子页面复用。本模块把与 UI 无关的数据层逻辑抽成独立函数，
供以下新增文件共用：
  - pages/1_语料浏览.py     语料浏览器（子页面）
  - pages/2_文献库管理.py   文献库管理（子页面）
  - db_check.py             语料库一致性检查脚本
  - eval/run_eval.py        评估脚本

本模块刻意保持"无 Streamlit 依赖"，可在纯命令行脚本中使用。
增强检索（A组 A7/A8/A9）实现在本模块的 search_chunks 中，app.py 与 eval 共用，
保证评测与线上行为同源：
  - A9 中文问题自动改写为多条英文/德文查询（rewrite_queries）
  - A7 向量 + Chroma 全文检索 RRF 融合（fulltext_query + _rrf_merge）
  - A8 bge-reranker-v2-m3 精排（rerank_documents，失败自动降级）
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter

import chromadb
import requests

from config import (
    BACKEND,
    CHROMA_DB_PATH,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_MODEL_LIGHT,
    EMBEDDING_MODEL,
    GLM_API_KEY,
    GLM_BASE_URL,
    GLM_MODEL,
    PRESS_TITLE_PREFIXES,
    RERANK_MODEL,
    SILICONFLOW_API_KEY,
    SILICONFLOW_BASE_URL,
    ZILLIZ_COLLECTION,
    ZILLIZ_TOKEN,
    ZILLIZ_URI,
)

# Light模式（streamlit run app.py -- -light）：查询改写用flash，排版修正用免费glm
LIGHT_MODE = any(a in ("-light", "--light") for a in sys.argv)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKDATA_PATH = os.path.join(PROJECT_DIR, "bookdata.json")
METADATA_PATH = os.path.join(PROJECT_DIR, "metadata.json")
COLLECTION_NAME = "habsburg"

_collection = None
_collection_lock = threading.Lock()

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_RRF_K = 60  # RRF 融合常数

# chroma sqlite 只读连接（全文检索FTS5直查用，不会与运行中的app写锁冲突）
_FTS_URI = "file:" + CHROMA_DB_PATH.replace("\\", "/") + "/chroma.sqlite3?mode=ro"


# ============================================================
# 资源加载
# ============================================================
def using_milvus():
    """当前后端是否为 Zilliz / Milvus"""
    return BACKEND == "zilliz"


def get_collection():
    """
    懒加载单例（进程内只打开一次）。

    BACKEND="chroma"（默认）→ 本地 ChromaDB 的 habsburg collection（原路径，可回滚）
    BACKEND="zilliz"        → Zilliz Cloud Serverless，经 milvus_backend.MilvusCollection
                              包装成同样的 count/get/query 接口，故上层调用点无需改动。
    """
    global _collection
    if _collection is None:
        with _collection_lock:
            if _collection is None:
                if using_milvus():
                    _missing = [n for n, v in (("ZILLIZ_URI", ZILLIZ_URI),
                                               ("ZILLIZ_TOKEN", ZILLIZ_TOKEN)) if not v]
                    if _missing:
                        raise RuntimeError(
                            "BACKEND=zilliz 但缺少：%s\n"
                            "  请在 config.py 中填写（★ 通常只需填 ZILLIZ_TOKEN 这一行），\n"
                            "  或设置同名环境变量。\n"
                            "  若要改用本地库，把 config.py 里的 BACKEND 改成 'chroma'。"
                            % "、".join(_missing)
                        )
                    from milvus_backend import MilvusCollection
                    _collection = MilvusCollection(ZILLIZ_URI, ZILLIZ_TOKEN, ZILLIZ_COLLECTION)
                else:
                    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
                    _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def load_bookdata():
    with open(BOOKDATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_content_metadata():
    """返回 {title: metadata.json条目} 的查找字典"""
    with open(METADATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {b["title"]: b for b in data}


def get_bookdata_lookup():
    return {b["title"]: b for b in load_bookdata()}


def get_series_lookup():
    """系列前缀 → bookdata 条目。报刊用法：chunk 的 title 是期号级
    （"Neue Freie Presse, 1864-09-01"），bookdata 里只有一条系列条目
    （title="Neue Freie Presse", title_prefix="Neue Freie Presse"）。"""
    out = {}
    for b in load_bookdata():
        p = b.get("title_prefix")
        if p:
            out[p] = b
    return out


def get_book_meta(title):
    """按title反查bookdata.json，找不到时返回占位数据而不是报错。

    ★ 两级查找：先精确匹配 title；未命中则按 title_prefix 回退到系列条目
      （报刊的期号级 title 靠这一步拿到系列级的作者/年代/描述）。
    """
    meta = get_bookdata_lookup().get(title)
    if meta is not None:
        return meta
    t = title or ""
    for prefix, series in get_series_lookup().items():
        if t.startswith(prefix):
            return series
    return {"title": title, "author": "未知", "year": "未知",
            "publisher": None, "description": None, "language": "未知"}


# ============================================================
# Embedding（SiliconFlow bge-m3，与 app.py 同款实现）
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
# 引用格式化与chunk富化（与 app.py 同款实现）
# ============================================================
_DOC_PREFIX_RE = re.compile(r"^\[([^\]]{3,100})\]")


def format_citation_tag(chunk_meta, text=None):
    """生成引用标注。三类形制：

      报刊      「Neue Freie Presse 1864-09-01, S. 2 (Ausland)」
      档案汇编   「ÖUA VIII, Nr. 10364」   —— 正文带 [卷次 · Nr. 编号 · 日期] 前缀
      其余史料   「(作者, 年份, p. 页码)」

    报刊判定放在最前：报刊 chunk 也有 doc_number（文章编号 A 2），
    但正文里没有档案前缀，若不先判会掉进「作者, 年份」分支，
    而报刊的「作者」是创办人，拿来做引注毫无意义。
    """
    title = chunk_meta.get("title") or ""

    # ---- 报刊（title 为期号级「系列名, YYYY-MM-DD」）----
    if is_press_title(title):
        m = re.match(r"^(?P<series>.+),\s*(?P<date>\d{4}-\d{2}-\d{2})$", title)
        series = m.group("series") if m else title
        date = m.group("date") if m else ""
        # 允许 bookdata 用 citation_name 指定更短的引注名（如 "NFP" / "《新自由报》"）
        name = get_book_meta(title).get("citation_name") or series
        cite = name + (" " + date if date else "")
        page = chunk_meta.get("page_num")
        if page and page != -1:
            cite += f", S. {page}"
        sec = chunk_meta.get("doc_section")
        if sec and sec != "Artikel":      # "Artikel" 是无栏目时的兜底，不必标
            cite += f" ({sec})"
        return cite

    # ---- 档案汇编 ----
    if chunk_meta.get("doc_number"):
        label = None
        if text:
            m = _DOC_PREFIX_RE.match(text.lstrip())
            if m:
                parts = [p.strip() for p in m.group(1).split("·")]
                if len(parts) >= 2 and parts[0]:
                    label = parts[0]
        if label:
            cite = f"{label}, Nr. {chunk_meta['doc_number']}"
            section = chunk_meta.get("doc_section")
            if section:
                cite += f" ({section})"
            return cite

    # ---- 其余史料 ----
    book = get_book_meta(chunk_meta["title"])
    author = book.get("author") or "未知作者"
    year = book.get("year") or "未知年份"
    page = chunk_meta.get("page_num")
    if page and page != -1:
        return f"{author}, {year}, p. {page}"
    return f"{author}, {year}"


def enrich_chunk(chunk_meta, text, relevance=None):
    """把chunk metadata和bookdata.json信息合并成一份完整的展示用字典"""
    book = get_book_meta(chunk_meta["title"])
    out = {
        "chunk_id": f"{chunk_meta.get('title','?')}::{chunk_meta.get('chunk_index','?')}",
        "chunk_index": chunk_meta.get("chunk_index"),
        "title": chunk_meta.get("title", "未知"),
        "source": chunk_meta.get("title", "未知"),
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
# DeepSeek 调用与查询改写（A9）
# ============================================================
def call_deepseek(messages, system_prompt="", temperature=0.3, max_tokens=4096,
                  model=None, api_key=None, base_url=None):
    """轻量OpenAI兼容chat调用（无tools），供查询改写、片段排版修正使用。
    model默认：light模式=DEEPSEEK_MODEL_LIGHT，否则=DEEPSEEK_MODEL。"""
    headers = {
        "Authorization": f"Bearer {api_key or DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or (DEEPSEEK_MODEL_LIGHT if LIGHT_MODE else DEEPSEEK_MODEL),
        "temperature": temperature,
        "messages": (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        ) + messages,
        "max_tokens": max_tokens,
    }
    try:
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{base_url or DEEPSEEK_API_URL}/chat/completions",
                    headers=headers, json=payload, timeout=60,
                )
                if resp.status_code == 429:
                    # 限流（智谱免费档常见）：退避后重试
                    time.sleep(2 ** attempt * 2)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"error": f"API 调用失败：{e}"}
        return {"error": "API 调用失败：429 限流（已重试3次仍被限流）"}
    except Exception as e:
        return {"error": f"API 调用失败：{e}"}


def rewrite_queries(question, max_queries=3):
    """
    把中文问题改写成多条英文/德文检索查询（A9）。
    失败或解析失败返回 None，调用方回退为只用原查询。

    语言配比说明：库内德文史料约占四分之一，且 ÖUA / MRP / Conrad 等一手档案
    全部为德文；早期版本只要求"英文查询，可选加一条德文"，实测导致中文问题
    完全检索不到德文档案，故改为强制至少一条德文查询。
    """
    prompt = (
        "把下面的用户问题改写为用于双语（英文 + 德文）历史文献库检索的查询。\n"
        "要求：\n"
        f"1. 输出2-{max_queries}条查询，其中**至少1条英文、至少1条德文**。\n"
        "   德文查询必须用德语书写（不要只是把英文词原样拼进去），"
        "因为库中的档案汇编、部长会议记录与回忆录原文均为德文；\n"
        "2. 专有名词（人名/地名/书名/条约名/机构名）保留原文语言，"
        "德文查询中对人名地名使用德文原拼写（如 Berchtold、Aehrenthal、Sarajevo）；\n"
        "3. 不要引入问题中没有的信息，不要回答或解释问题本身；\n"
        "4. 严格输出JSON字符串数组，例如："
        '["English query", "Deutsche Anfrage"]\n\n'
        f"问题：{question}"
    )
    # max_tokens给足：deepseek-v4-pro是推理模型，会先消耗reasoning token，
    # 太小会导致finish_reason=length且content为空
    resp = call_deepseek([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=2048)
    if "error" in resp:
        return None
    raw = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
        queries = [q.strip() for q in arr if isinstance(q, str) and q.strip()]
        return queries[:max_queries] or None
    except Exception:
        return None


# ============================================================
# 检索增强：where构建 / 全文 / RRF / rerank（A7/A8/A9）
# ============================================================
def is_press_title(title):
    """判断某个 title 是否属于报刊系列（按期号级 title 的前缀匹配）。"""
    t = title or ""
    return any(t.startswith(p) for p in PRESS_TITLE_PREFIXES)


def build_where(source_type=None, region=None, lang=None, subfield=None,
                stance=None, title=None, exclude_press=False, exclude=None):
    """
    构建Chroma where条件。
    region/subfield 支持单值或列表（多选语义=任一匹配，用$or实现）。

    exclude_press=True 时追加 title 前缀否定条件，把报刊挡在检索之外。
    两条腿（稠密 search_dense / 稀疏 search_sparse）共用同一个 where，
    所以在这里加一次即可；本地 FTS5 腿不走 where，需在 _meta_matches 里同步。

    exclude：负过滤，{字段名: [要排除的值, ...]}，供「文献查找」模式用。
      ★ 每个条件都写成 `字段 NOT IN [...] OR 字段 IS NULL`。
        Milvus 的 NULL 三值逻辑下 `x != 'y'` 对 NULL 行返回 UNKNOWN（不是 TRUE），
        直接写 not in 会把所有该字段为 NULL 的行一并排除 —— 实测这类行在现有
        语料里是绝大多数（例如 doc_section 只有 MRP/ÖUA/报刊有值）。
        加 `or is null` 才是正确的「排除某值」，而不是「排除没这个值的行」。
    """
    conds = []
    if source_type:
        conds.append({"source_type": {"$eq": source_type}})
    if region:
        if isinstance(region, (list, tuple, set)) and region:
            conds.append({"$or": [{"region": {"$contains": r}} for r in region]})
        else:
            conds.append({"region": {"$contains": region}})
    if subfield:
        if isinstance(subfield, (list, tuple, set)) and subfield:
            conds.append({"$or": [{"subfield": {"$contains": s}} for s in subfield]})
        else:
            conds.append({"subfield": {"$contains": subfield}})
    if lang:
        conds.append({"language": {"$eq": lang}})
    if title:
        conds.append({"title": {"$eq": title}})
    if stance:
        conds.append({"stance": {"$eq": stance}})
    if exclude_press:
        for p in PRESS_TITLE_PREFIXES:
            conds.append({"title": {"$not_like": p + "%"}})
    if exclude:
        for field, vals in exclude.items():
            vals = [v for v in (vals or []) if v not in (None, "")]
            if not vals:
                continue
            if field in ("region", "subfield"):
                # 数组字段：逐个值取反（多个条件 AND = 一个都不许出现）
                for v in vals:
                    conds.append({"$or": [{field: {"$not_contains": v}},
                                          {field: {"$is_null": True}}]})
            else:
                conds.append({"$or": [{field: {"$nin": vals}},
                                      {field: {"$is_null": True}}]})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


_FULLTEXT_OK = False  # 最近一次全文检索是否成功
_FULLTEXT_ERR = None  # 最近一次全文检索失败原因（供开发者模式排查）


def _meta_matches(meta, source_type=None, region=None, lang=None, subfield=None,
                  stance=None, title=None, exclude_press=False, exclude=None):
    """Python侧的过滤条件判定，与 build_where 语义一致（供全文腿结果过滤用）。

    ★ exclude_press / exclude 必须与 build_where 同步：本地后端的 FTS5 全文腿
      拿不到 where 条件（它是直查 sqlite 再在 Python 里过滤），漏了这里就等于
      本地后端的过滤完全失效。
    ★ exclude 的语义同样是「排除该值，但保留该字段为 NULL 的行」（见 build_where）。
    """
    if exclude_press and is_press_title(meta.get("title")):
        return False
    if exclude:
        for field, vals in exclude.items():
            vals = [v for v in (vals or []) if v not in (None, "")]
            if not vals:
                continue
            mv = meta.get(field)
            if field in ("region", "subfield"):
                if any(v in (mv or []) for v in vals):
                    return False
            elif mv is not None and mv in vals:
                return False
    if source_type and meta.get("source_type") != source_type:
        return False
    if region:
        regions = list(region) if isinstance(region, (list, tuple, set)) else [region]
        meta_regions = meta.get("region") or []
        if not any(r in meta_regions for r in regions):
            return False
    if subfield:
        subfields = list(subfield) if isinstance(subfield, (list, tuple, set)) else [subfield]
        meta_sub = meta.get("subfield") or []
        if not any(s in meta_sub for s in subfields):
            return False
    if lang and meta.get("language") != lang:
        return False
    if stance and meta.get("stance") != stance:
        return False
    if title and meta.get("title") != title:
        return False
    return True


def fulltext_query(query_text, source_type=None, region=None, lang=None, subfield=None,
                   stance=None, title=None, n_results=10, exclude_press=False,
                   exclude=None):
    """
    全文检索腿（A7）：sqlite FTS5（trigram分词器）直查 + Python侧过滤。
    chroma的query_texts API在本collection不可用，故直接查库内FTS表：
      embedding_fulltext_search(rowid, string_value) 的 rowid == embeddings.id，
      再经 embeddings.embedding_id 得到 chunk_id。
    查询串先做 FTS5 语法清洗（见下），再 ORDER BY rank 取相关度最高的若干行。
    返回按FTS相关度排序的 [(meta, doc), ...]；任何异常返回 []（静默降级，
    失败原因记入 _FULLTEXT_ERR，仅开发者模式可见）。
    """
    global _FULLTEXT_OK, _FULLTEXT_ERR
    _FULLTEXT_ERR = None
    # FTS5 的查询语法把 . , - / ( ) * : 等字符当保留字，直接塞进 MATCH 会抛
    # fts5: syntax error 并被下面的 except 静默吞掉，导致整条腿失效
    # （例如 Nr. 10364 / 1914-07-06 / K.u.k. / (Conrad, 1921, p. 284) 全部命中不了）。
    # 这里把所有非单词字符统一替换为空格；\w 在 Python 3 默认 Unicode，
    # 变音符（ö/ć）与中日韩汉字都会保留，语义等价于拆成若干 bareword 做 AND 匹配。
    q = re.sub(r"[^\w]+", " ", query_text or "").strip()
    if not q:
        _FULLTEXT_OK = True  # 没有可检索的词 ≠ 检索失败，不应误报降级
        return []
    try:
        con = sqlite3.connect(_FTS_URI, uri=True, timeout=5)
        rows = con.execute(
            "SELECT rowid FROM embedding_fulltext_search "
            "WHERE embedding_fulltext_search MATCH ? ORDER BY rank LIMIT ?",
            (q, max(n_results * 3, 50)),
        ).fetchall()
        con.close()
    except Exception as e:
        _FULLTEXT_OK = False
        _FULLTEXT_ERR = f"{type(e).__name__}: {e}"
        return []
    if not rows:
        _FULLTEXT_OK = True
        return []
    fts_ids = [r[0] for r in rows]
    try:
        con = sqlite3.connect(_FTS_URI, uri=True, timeout=5)
        ph = ",".join("?" for _ in fts_ids)
        id_rows = con.execute(
            f"SELECT id, embedding_id FROM embeddings WHERE id IN ({ph})", fts_ids
        ).fetchall()
        con.close()
    except Exception as e:
        _FULLTEXT_OK = False
        _FULLTEXT_ERR = f"{type(e).__name__}: {e}"
        return []
    id_to_chunk = {r[0]: r[1] for r in id_rows}
    chunk_ids = [id_to_chunk[i] for i in fts_ids if i in id_to_chunk]
    if not chunk_ids:
        _FULLTEXT_OK = True
        return []
    try:
        res = get_collection().get(ids=chunk_ids, include=["documents", "metadatas"])
    except Exception as e:
        _FULLTEXT_OK = False
        _FULLTEXT_ERR = f"{type(e).__name__}: {e}"
        return []
    by_cid = {}
    for cid, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        by_cid[cid] = (meta, doc)
    out = []
    for cid in chunk_ids:  # 按FTS相关度顺序输出
        pair = by_cid.get(cid)
        if pair and _meta_matches(pair[0], source_type, region, lang, subfield, stance,
                                  title, exclude_press, exclude):
            out.append(pair)
        if len(out) >= n_results:
            break
    _FULLTEXT_OK = True
    return out


def _chunk_id_of(meta):
    return f"{meta.get('title','?')}::{meta.get('chunk_index','?')}"


def _rrf_merge(ranked_lists, k=_RRF_K):
    """
    Reciprocal Rank Fusion：合并多条排序列表。
    每条列表元素为 (meta, doc) 或 (meta, doc, score) 元组。
    返回 [(meta, doc, rrf_score), ...] 按融合分降序。
    """
    scores, best = {}, {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            meta, doc = item[0], item[1]
            cid = _chunk_id_of(meta)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in best:
                best[cid] = (meta, doc)
    order = sorted(scores, key=lambda c: scores[c], reverse=True)
    return [(best[c][0], best[c][1], scores[c]) for c in order]


def rerank_documents(query, documents, top_n):
    """
    bge-reranker-v2-m3 精排（A8）。返回 [(输入文档下标, score), ...]；
    任何失败返回 None，调用方回退到原排序。
    """
    if not documents:
        return []
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }
    try:
        resp = requests.post(
            f"{SILICONFLOW_BASE_URL}/rerank",
            headers=headers, json=payload, timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        scored = []
        for r in results:
            i = r.get("index", -1)
            if isinstance(i, int) and 0 <= i < len(documents):
                scored.append((i, float(r.get("relevance_score", 0.0))))
        return scored or None
    except Exception:
        return None


def search_chunks(query, source_type=None, region=None, lang=None, subfield=None,
                  stance=None, title=None, n_results=10, excluded=None,
                  use_hybrid=True, use_rerank=True, use_rewrite=True,
                  include_press=False, exclude=None, debug_log=None):
    """
    增强版语义检索（app.py tool_search_corpus 与 eval 共用的同源实现）。

    流程：A9 查询改写（仅含中文时）→ 每条查询并行跑 A7 向量+全文RRF →
    跨查询再次RRF融合 → A8 rerank精排（可降级）→ 过滤excluded → 截断top-n。

    region/subfield 可为单值或多值列表；excluded 为chunk_id集合。
    include_press=False（默认）时把报刊（config.PRESS_TITLE_PREFIXES）挡在
      检索之外 —— 报刊体量是其余语料的 10 倍以上，默认纳入会稀释结果。
      是否开启由 **agent** 通过工具参数决定，不是用户开关。
    exclude：负过滤 {字段: [要排除的值]}，语义见 build_where（NULL 安全）。
    debug_log: 可选回调 debug_log({"title":..., "text":..., "is_json":...})，
    供开发者模式记录检索中间步骤。
    """
    def _dbg(title, payload):
        if debug_log:
            try:
                debug_log({"title": title, "text": json.dumps(payload, ensure_ascii=False, indent=2), "is_json": True})
            except Exception:
                pass

    collection = get_collection()
    where = build_where(source_type=source_type, region=region, lang=lang,
                        subfield=subfield, stance=stance, title=title,
                        exclude_press=not include_press, exclude=exclude)

    # ---- A9 查询改写：仅中文问题触发 ----
    queries = [query]
    if use_rewrite and CJK_RE.search(query or ""):
        rewritten = rewrite_queries(query)
        if rewritten:
            queries.extend(q for q in rewritten if q not in queries)
            queries = queries[:4]  # 原查询 + 最多3条改写
    _dbg("检索增强 · 查询改写", {"original": query, "queries": queries})

    # ---- 每条查询：A7 向量 + 全文 RRF ----
    # 两条腿按后端分派：
    #   本地：collection.query（Chroma 向量）+ fulltext_query（FTS5 trigram 子串）
    #   云端：search_dense（稠密）+ search_sparse（BM25 稀疏向量，data 传原始查询文本）
    # 融合逻辑（_rrf_merge，k=60）两种后端完全相同，便于 A/B 对比。
    per_query_lists = []
    dist_map = {}  # chunk_id -> 向量距离（用于未rerank时的relevance）
    _milvus = using_milvus()
    if _milvus:
        from milvus_backend import row_to_meta as _row_to_meta
    cand = min(n_results * 3, 100)

    def _hits_to_tuples(hits):
        """Milvus 命中 → [(meta, doc, dist), ...]，与 Chroma 腿同构"""
        out = []
        for h in hits:
            ent = h["entity"]
            out.append((_row_to_meta(ent), ent.get("text", ""), h["distance"]))
        return out

    for q in queries:
        vec, ft = [], []
        try:
            q_emb = embed_text(q)
            if _milvus:
                vec = _hits_to_tuples(collection.search_dense(q_emb, where=where, limit=cand))
            else:
                res = collection.query(
                    query_embeddings=[q_emb], where=where,
                    n_results=cand,
                    include=["documents", "metadatas", "distances"],
                )
                vec = list(zip(res["metadatas"][0], res["documents"][0], res["distances"][0]))
            for meta, _doc, dist in vec:
                cid = _chunk_id_of(meta)
                if cid not in dist_map or dist < dist_map[cid]:
                    dist_map[cid] = dist
        except Exception as e:
            _dbg("检索增强 · 向量检索失败", {"query": q, "error": str(e)})

        if use_hybrid:
            try:
                if _milvus:
                    ft = _hits_to_tuples(collection.search_sparse(q, where=where, limit=cand))
                else:
                    ft = fulltext_query(q, source_type=source_type, region=region, lang=lang,
                                        subfield=subfield, stance=stance, title=title,
                                        n_results=cand, exclude_press=not include_press,
                                        exclude=exclude)
            except Exception as e:
                _dbg("检索增强 · 全文检索失败", {"query": q, "error": str(e)})
                ft = []

        if vec and ft:
            per_query_lists.append(_rrf_merge([vec, ft]))
        elif vec:
            per_query_lists.append(_rrf_merge([vec]))
        elif ft:
            per_query_lists.append(_rrf_merge([ft]))
    _dbg("检索增强 · 全文检索", {"backend": BACKEND, "enabled": use_hybrid,
                                 "available": True if _milvus else _FULLTEXT_OK,
                                 "error": None if _milvus else _FULLTEXT_ERR})

    if not per_query_lists:
        return []

    # ---- 跨查询融合 ----
    fused = _rrf_merge(per_query_lists)

    # ---- A8 rerank 精排（失败降级为RRF顺序）----
    # 用全部查询（原查询 + A9 改写）分别精排并取每篇的最高分。
    # 原因：精排分数对查询语言敏感——中文查询给英文论著 ~0.98、给德文档案原件仅 ~0.3；
    # 改用德文查询后同一份德文档案可得 ~0.96。只拿原查询精排会把德文一手史料整体压下去。
    rerank_used = False
    candidates = fused[:max(30, n_results * 3)]
    if use_rerank and len(candidates) > 1:
        docs = [doc for _meta, doc, _s in candidates]
        top_n = min(30, len(docs))
        best = {}
        for q in queries:
            scored = rerank_documents(q, docs, top_n)
            if scored:
                for i, v in scored:
                    if v > best.get(i, -1.0):
                        best[i] = v
        if best:
            ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
            candidates = [(candidates[i][0], candidates[i][1], s) for i, s in ranked]
            rerank_used = True
    _dbg("检索增强 · rerank精排", {"enabled": use_rerank, "used": rerank_used,
                                    "candidates": len(candidates)})

    # ---- 过滤excluded + 富化输出 ----
    excluded = excluded or set()
    output = []
    for meta, doc, score in candidates:
        cid = _chunk_id_of(meta)
        if cid in excluded:
            continue
        if rerank_used:
            relevance = round(score, 3)
        else:
            relevance = round(1 - dist_map.get(cid, 0.0), 3)
        output.append(enrich_chunk(meta, doc, relevance=relevance))
        if len(output) >= n_results:
            break
    return output


# ============================================================
# 书目/片段批量读取（供浏览页与管理页、一致性检查使用）
# ============================================================
def get_book_counts():
    """
    返回 {title: chunk数} 的Counter。
    利用chunk_id格式 title::chunk_index 直接从id解析，一次get()即可，无需逐书查询。
    """
    ids = get_collection().get(include=[])["ids"]
    counts = Counter()
    for cid in ids:
        counts[cid.rsplit("::", 1)[0]] += 1
    return counts


def get_chunks_for_book(title):
    """返回某本书的全部chunk（按chunk_index升序，已富化），供语料浏览使用"""
    result = get_collection().get(
        where={"title": {"$eq": title}}, include=["documents", "metadatas"]
    )
    pairs = sorted(
        zip(result["documents"], result["metadatas"]),
        key=lambda x: x[1].get("chunk_index", 0),
    )
    return [enrich_chunk(meta, doc) for doc, meta in pairs]


def get_chapters_for_book(title):
    """返回某本书的全部非空章节标题（升序列表）"""
    result = get_collection().get(where={"title": {"$eq": title}}, include=["metadatas"])
    return sorted({m.get("chapter_title") for m in result["metadatas"] if m.get("chapter_title")})


def get_chunks_by_ids(chunk_ids):
    """
    按chunk_id列表批量取回富化后的片段（{chunk_id: chunk字典}）。
    已不存在的id会被静默跳过；供对话历史按id还原原文使用。
    """
    ids = [c for c in chunk_ids if c]
    if not ids:
        return {}
    result = get_collection().get(ids=ids, include=["documents", "metadatas"])
    out = {}
    for cid, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
        out[cid] = enrich_chunk(meta, doc)
    return out


# ============================================================
# 展示文本修正：flash 轻量模型 + 磁盘缓存（纯展示层，不改库）
# ============================================================
FIX_SYSTEM_PROMPT = (
    "你是古籍扫描文本的校对员。原文本来自PDF/EPUB提取或OCR，带有换行错误、断词、"
    "拼写错误等噪声。请修复这些噪声，输出可直接阅读的干净文本。"
)

FIX_RULES = (
    "修正规则（务必遵守）：\n"
    "1. 修复错误的换行：把句子中途被截断的行合并为连贯段落；修复行尾连字符断词"
    "（如 Austro-\\nHungarian → Austro-Hungarian）\n"
    "2. 修复明显的OCR/扫描拼写错误（如 rhrough→through、字母与数字混用、丢失空格等）\n"
    "3. 可以轻微理顺标点与语序，但必须相当保守：不得改变原意，不得增删任何信息"
    "（人名、地名、数字、日期、页码、书名、引文一律原样保留）\n"
    "4. 不得翻译，保持原文语言（英文/德文/波兰文等）\n"
    "5. 不得添加任何解释、评论、标题或markdown格式\n"
    "6. 直接输出修正后的完整文本，与原文一一对应，不要输出其他任何文字\n\n"
    "原文：\n"
)

_TF_CACHE_PATH = os.path.join(PROJECT_DIR, "textfix_cache.json")
_tf_cache = None
_tf_cache_lock = threading.Lock()


def _load_textfix_cache():
    global _tf_cache
    if _tf_cache is None:
        with _tf_cache_lock:
            if _tf_cache is None:
                try:
                    with open(_TF_CACHE_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                    _tf_cache = data if isinstance(data, dict) else {}
                except Exception:
                    _tf_cache = {}
    return _tf_cache


def _save_textfix_cache():
    try:
        with open(_TF_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_load_textfix_cache(), f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # 写盘失败不影响功能，仅损失跨进程缓存


def fix_display_text(text):
    """
    修正片段排版/拼写（保守润色）：light模式用免费glm-4.7-flash，否则用deepseek-v4-flash。
    返回修正后文本；任何失败返回 None（调用方回退原文）。
    """
    if not text or not text.strip():
        return None
    if LIGHT_MODE:
        kwargs = {"model": GLM_MODEL, "api_key": GLM_API_KEY, "base_url": GLM_BASE_URL}
    else:
        kwargs = {"model": DEEPSEEK_MODEL_LIGHT}
    resp = call_deepseek(
        [{"role": "user", "content": FIX_RULES + text}],
        system_prompt=FIX_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=8192,
        **kwargs,
    )
    if "error" in resp:
        return None
    out = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not out:
        return None
    # 防御：模型偶尔用成对引号包住全文，去掉首尾引号
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    return out or None


def _unit_cache_key(unit):
    ids = unit.get("all_chunk_ids") or ([unit.get("chunk_id")] if unit.get("chunk_id") else [])
    return json.dumps(ids, ensure_ascii=False)


_MERGE_SEP = "\n\n···\n\n"  # 与 app.merge_adjacent_chunks 的合并分隔符一致


def _fix_segments(text, max_workers=4):
    """
    把展示单元文本按合并分隔符拆成单段（每段≈一个chunk，≤500词）分别修正再拼回。
    整段一次调用容易超长（合并单元可达数千词），分段后每段调用小、可并行、更稳。
    """
    parts = text.split(_MERGE_SEP)
    if len(parts) == 1:
        return fix_display_text(text)
    from concurrent.futures import ThreadPoolExecutor

    workers = min(max_workers, 2) if LIGHT_MODE else max_workers  # 免费glm限流，降低并发
    todo = [(i, p) for i, p in enumerate(parts) if p.strip()]
    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as ex:
        results = list(ex.map(lambda item: (item[0], fix_display_text(item[1])), todo))
    for i, fixed in results:
        parts[i] = fixed if fixed else parts[i]
    return _MERGE_SEP.join(parts)


def get_corrected_text(unit):
    """
    返回展示单元修正后的文本（自动修正 + 磁盘缓存，键=该单元全部chunk_id）。
    缓存未命中时调用 flash；失败回退原文。任何异常都不影响展示。
    """
    text = unit.get("text") or ""
    if not text.strip():
        return text
    key = _unit_cache_key(unit)
    cache = _load_textfix_cache()
    if key in cache and cache[key]:
        return cache[key]
    fixed = _fix_segments(text)
    if not fixed:
        return text
    with _tf_cache_lock:
        _load_textfix_cache()[key] = fixed
    _save_textfix_cache()
    return fixed


def correct_units(units, max_workers=4, progress_cb=None):
    """
    并行预修正多个展示单元（只对缓存未命中的单元调用 flash）。
    合并单元按分隔符拆段修正，全部段成功才写入缓存。
    返回本次新修正的单元数。供渲染前批量预热，避免逐条串行等待。

    progress_cb(done, total, key)：某个单元的全部段落都修正完成后回调一次。
    供调用方做「先出原文、再逐条回填」的实时展示（文献查找模式用），
    回调异常一律吞掉，绝不影响展示。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache = _load_textfix_cache()
    tasks = []
    for u in units:
        key = _unit_cache_key(u)
        text = u.get("text") or ""
        if not text.strip() or (key in cache and cache[key]):
            continue
        tasks.append((key, text.split(_MERGE_SEP)))

    if not tasks:
        return 0

    seg_tasks = []
    for key, parts in tasks:
        for si, seg in enumerate(parts):
            if seg.strip():
                seg_tasks.append((key, si, seg))

    def _work(item):
        key, si, seg = item
        return key, si, fix_display_text(seg)

    parts_by_key = dict(tasks)
    seg_total, seg_done = {}, {}
    for key, _si, _seg in seg_tasks:
        seg_total[key] = seg_total.get(key, 0) + 1

    fixed_map = {}
    fixed_n = 0
    workers = min(max_workers, 2) if LIGHT_MODE else max_workers  # 免费glm限流，降低并发
    with ThreadPoolExecutor(max_workers=min(workers, len(seg_tasks))) as ex:
        futures = [ex.submit(_work, t) for t in seg_tasks]
        for fut in as_completed(futures):
            try:
                key, si, fixed = fut.result()
            except Exception:
                # 单段失败：该单元最终判为「不成功」，展示时回退原文（不写缓存）
                continue
            fixed_map.setdefault(key, {})[si] = fixed
            seg_done[key] = seg_done.get(key, 0) + 1
            if seg_done[key] != seg_total.get(key):
                continue                      # 该单元还有段没回来
            parts = parts_by_key.get(key) or []
            if not all(fixed_map.get(key, {}).get(i)
                       for i in range(len(parts)) if parts[i].strip()):
                continue
            rebuilt = [fixed_map.get(key, {}).get(i) or parts[i] for i in range(len(parts))]
            with _tf_cache_lock:
                _load_textfix_cache()[key] = _MERGE_SEP.join(rebuilt)
            fixed_n += 1
            if progress_cb:
                try:
                    progress_cb(fixed_n, len(tasks), key)
                except Exception:
                    pass
    if fixed_n:
        _save_textfix_cache()
    return fixed_n
