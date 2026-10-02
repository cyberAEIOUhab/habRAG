"""
ingest.py —— 哈布斯堡史RAG系统 重构版语料入库脚本

功能：
1. 读取 bookdata.json（书籍基础信息，权威来源）
2. 读取 metadata.json（内容级判断，stance/subfield/period/region/source_type）
3. 提取PDF/EPUB/DOCX正文，按位置聚合block（PyMuPDF get_text("blocks")模式）
4. 过滤噪声block（同书内重复出现>=3次的短block，通常是页眉页脚）
5. 按词数规则切分chunk，并加50-100词的overlap
6. 用chunk的page_num去匹配metadata.json的章节页码区间，分配chapter_title等字段
7. 调用SiliconFlow bge-m3 API做embedding（批量）
8. 写入ChromaDB（新collection，1024维）

运行前置条件：
- chromadb >= 1.5.0（array metadata + $contains过滤需要这个版本）
- pip install pymupdf ebooklib python-docx chromadb requests --break-system-packages（如适用）
- config.py 中已配置 SILICONFLOW_API_KEY / SILICONFLOW_BASE_URL / EMBEDDING_MODEL / CHROMA_DB_PATH

支持断点续跑：按书为单位记录进度，中途中断后重跑会跳过已完成的书。
"""

import os
import re
import sys
import json
import time
import traceback
from collections import Counter

import fitz  # PyMuPDF
import requests
import chromadb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    SILICONFLOW_API_KEY,
    SILICONFLOW_BASE_URL,
    EMBEDDING_MODEL,
    CHROMA_DB_PATH,
)
# ★ 统一从 corpus_lib 取 collection：它按 config.BACKEND 分派（chroma 本地 / zilliz 云端）。
#   不要在这里自建 chromadb.PersistentClient，那会绕过后端开关。
from corpus_lib import get_collection

# ============================================================
# 路径配置
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKDATA_PATH = os.path.join(PROJECT_DIR, "bookdata.json")
METADATA_PATH = os.path.join(PROJECT_DIR, "metadata.json")
SOURCE_DIR = r"C:\Users\notch\Desktop\哈布斯堡史"  # 原文件目录，未随项目迁移

COLLECTION_NAME = "habsburg"
LOG_PATH = os.path.join(PROJECT_DIR, "ingest_log.txt")
PROCESSED_PATH = os.path.join(PROJECT_DIR, "ingest_processed.txt")

# ============================================================
# 分块参数
# ============================================================
MIN_BLOCK_WORDS = 5        # 过滤词数<5的碎片block
MERGE_THRESHOLD = 100       # <100词的块尝试与下一块合并
MERGE_CAP = 600             # 合并后超过600词就不再合并
DIRECT_MAX = 500            # 100-500词直接输出
SUBCHUNK_MAX = 500          # >500词按句子边界切分，子块<=500词
OVERLAP_WORDS = 75          # chunk之间的滑动重叠窗口
NOISE_REPEAT_THRESHOLD = 3  # 同一本书内完全重复出现>=3次的block视为噪声（页眉页脚等）
NOISE_MAX_WORDS = 20        # 只对<=20词的block做重复噪声判定，避免误删重复出现的长引文/题记
EMBED_BATCH_SIZE = 16       # 每次调用embedding API的文本数量

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+|[\u4e00-\u9fff]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s*")
HYPHEN_RE = re.compile(r"(\w)-\n(\w)")

REGION_CANDIDATES = {
    "全帝国",
    "下奥地利", "上奥地利", "萨尔茨堡", "施泰尔马克", "克恩顿", "克赖恩",
    "蒂罗尔-福拉尔贝格", "滨海地区", "波希米亚", "摩拉维亚", "奥属西里西亚",
    "加利西亚", "布科维纳", "达尔马提亚",
    "匈牙利本土", "特兰西瓦尼亚", "克罗地亚-斯拉沃尼亚", "斯洛伐克地区",
    "伏伊伏丁那/巴纳特", "阜姆",
    "波斯尼亚-黑塞哥维那",
    "德意志地区", "巴尔干地区", "奥斯曼帝国", "俄罗斯帝国", "意大利", "波兰",
}


# ============================================================
# 日志与断点续跑
# ============================================================
def load_processed():
    if not os.path.exists(PROCESSED_PATH):
        return set()
    with open(PROCESSED_PATH, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def mark_processed(title):
    with open(PROCESSED_PATH, "a", encoding="utf-8") as f:
        f.write(title + "\n")


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================
# 文本工具
# ============================================================
def count_words(text):
    return len(WORD_RE.findall(text))


def fix_hyphenation(text):
    return HYPHEN_RE.sub(r"\1\2", text)


def get_overlap_text(text, n_words=OVERLAP_WORDS):
    """取text结尾大约n_words个词，用于下一个chunk的overlap前缀（近似算法）"""
    matches = list(WORD_RE.finditer(text))
    if len(matches) <= n_words:
        return text
    start_idx = matches[-n_words].start()
    return text[start_idx:]


# ============================================================
# 第一部分：文本提取（PDF / EPUB / DOCX）
# 每本书返回 List[{"page_num": int|None, "text": str}]
# page_num对PDF是真实页码；EPUB/DOCX没有页码概念，统一填None
# ============================================================
def extract_pdf_blocks(filepath):
    blocks_out = []
    doc = fitz.open(filepath)
    for page_index in range(len(doc)):
        page = doc[page_index]
        for b in page.get_text("blocks"):
            text = fix_hyphenation(b[4]).strip()
            if not text:
                continue
            blocks_out.append({"page_num": page_index + 1, "text": text})
    doc.close()
    return blocks_out


def extract_docx_blocks(filepath):
    import docx
    d = docx.Document(filepath)
    blocks_out = []
    for para in d.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        blocks_out.append({"page_num": None, "text": text})
    return blocks_out


def extract_epub_blocks(filepath):
    import ebooklib
    from ebooklib import epub
    book = epub.read_epub(filepath)
    blocks_out = []
    tag_re = re.compile(r"<[^>]+>")
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        html = item.get_content().decode("utf-8", errors="ignore")
        text = tag_re.sub("\n", html)
        for para in re.split(r"\n{2,}", text):
            para = para.strip()
            if para:
                blocks_out.append({"page_num": None, "text": para})
    return blocks_out


def extract_blocks(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return extract_pdf_blocks(filepath)
    elif ext == ".docx":
        return extract_docx_blocks(filepath)
    elif ext == ".epub":
        return extract_epub_blocks(filepath)
    else:
        raise ValueError(f"不支持的文件格式：{ext}")


# ============================================================
# 第二部分：噪声过滤 + 分块 + overlap
# ============================================================
def filter_short_blocks(blocks):
    return [b for b in blocks if count_words(b["text"]) >= MIN_BLOCK_WORDS]


def filter_noise_blocks(blocks):
    """
    同一本书内完全重复出现>=3次的【短】block视为页眉页脚等噪声，整体丢弃。
    只对<=NOISE_MAX_WORDS词的block做判定，避免误删重复出现的长引文/题记等有价值内容。
    """
    short_texts = [b["text"] for b in blocks if count_words(b["text"]) <= NOISE_MAX_WORDS]
    counter = Counter(short_texts)
    noise_texts = {t for t, c in counter.items() if c >= NOISE_REPEAT_THRESHOLD}
    if noise_texts:
        log(f"  过滤噪声block：{len(noise_texts)}种，共{sum(counter[t] for t in noise_texts)}次出现")
    return [b for b in blocks if b["text"] not in noise_texts]


def hard_split_by_words(text, max_words=SUBCHUNK_MAX):
    """兜底：没有句末标点可切时（如OCR断句丢失），按词数硬切，避免子块无限膨胀"""
    matches = list(WORD_RE.finditer(text))
    if len(matches) <= max_words:
        return [text]
    pieces, start_char = [], 0
    for i in range(max_words, len(matches), max_words):
        cut = matches[i].start()
        pieces.append(text[start_char:cut].strip())
        start_char = cut
    tail = text[start_char:].strip()
    if tail:
        pieces.append(tail)
    return [p for p in pieces if p]


def split_long_block(text, page_num):
    sentences = SENTENCE_SPLIT_RE.split(text)
    subchunks, current = [], ""
    for s in sentences:
        candidate = (current + s) if current else s
        if count_words(candidate) > SUBCHUNK_MAX and current:
            subchunks.append(current.strip())
            current = s
        else:
            current = candidate
    if current.strip():
        subchunks.append(current.strip())

    # 兜底：句子切分后仍有块超出上限（通常是缺少句末标点导致切不动），按词数硬切
    # 严格执行"子块<=500词"的规范
    final = []
    for c in subchunks:
        if count_words(c) > SUBCHUNK_MAX:
            final.extend(hard_split_by_words(c))
        else:
            final.append(c)
    return [{"page_num": page_num, "text": c} for c in final]


def build_chunks(blocks):
    """按词数规则合并/切分blocks，生成chunk列表（尚未加overlap）"""
    chunks = []
    i, n = 0, len(blocks)
    while i < n:
        b = blocks[i]
        wc = count_words(b["text"])
        if wc > DIRECT_MAX:
            chunks.extend(split_long_block(b["text"], b["page_num"]))
            i += 1
        elif wc < MERGE_THRESHOLD:
            merged_text = b["text"]
            merged_page = b["page_num"]
            j = i + 1
            while j < n:
                candidate = merged_text + "\n" + blocks[j]["text"]
                if count_words(candidate) > MERGE_CAP:
                    break
                merged_text = candidate
                j += 1
                if count_words(merged_text) >= MERGE_THRESHOLD:
                    break
            chunks.append({"page_num": merged_page, "text": merged_text})
            i = j
        else:
            chunks.append({"page_num": b["page_num"], "text": b["text"]})
            i += 1
    return chunks


def add_overlap(chunks):
    """给每个chunk（除第一个）前面拼接上一个chunk结尾约OVERLAP_WORDS个词"""
    result = []
    for idx, c in enumerate(chunks):
        if idx == 0:
            result.append(dict(c))
            continue
        prev_text = chunks[idx - 1]["text"]
        overlap_text = get_overlap_text(prev_text, OVERLAP_WORDS)
        result.append({"page_num": c["page_num"], "text": overlap_text + "\n" + c["text"]})
    return result


# ============================================================
# 第三部分：metadata.json 章节匹配
# ============================================================
def load_content_metadata():
    with open(METADATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {b["title"]: b for b in data}


def get_fields_for_chunk(book_meta, page_num):
    """
    返回该chunk应有的 stance/subfield/period/region/source_type/chapter_title
    book_meta: metadata.json中该书对应的字典
    page_num: 该chunk的页码（PDF有值，EPUB/DOCX为None）
    """
    stance = book_meta.get("stance")

    if book_meta["granularity"] == "book":
        return {
            "stance": stance,
            "subfield": book_meta.get("subfield", []),
            "period": book_meta.get("period"),
            "region": book_meta.get("region", []),
            "source_type": book_meta.get("source_type"),
            "chapter_title": None,
        }

    chapters = book_meta.get("chapters", [])

    # 有真实页码：按页码区间匹配
    if page_num is not None:
        for ch in chapters:
            if ch["start_page"] <= page_num <= ch["end_page"]:
                return {
                    "stance": stance,
                    "subfield": ch.get("subfield", []),
                    "period": ch.get("period"),
                    "region": ch.get("region", []),
                    "source_type": ch.get("source_type"),
                    "chapter_title": ch.get("chapter_title"),
                }
        # 页码没落在任何章节区间（如前言/扉页），退回聚合值

    # 没有页码（EPUB/DOCX）或没匹配到章节：聚合全部章节的字段作为近似值
    all_subfield = sorted({s for ch in chapters for s in ch.get("subfield", [])})
    all_region = sorted({r for ch in chapters for r in ch.get("region", [])})
    periods = [ch.get("period") for ch in chapters if ch.get("period")]
    period = _merge_periods(periods)
    source_types = [ch.get("source_type") for ch in chapters if ch.get("source_type")]
    source_type = Counter(source_types).most_common(1)[0][0] if source_types else None

    return {
        "stance": stance,
        "subfield": all_subfield,
        "period": period,
        "region": all_region,
        "source_type": source_type,
        "chapter_title": None,  # 无法定位具体章节，标注为空
    }


def _merge_periods(periods):
    """把多个YYYY-YYYY/YYYY取并集范围，仍输出合规格式"""
    years = []
    for p in periods:
        parts = p.split("-")
        years.extend(int(x) for x in parts)
    if not years:
        return None
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else f"{lo}-{hi}"


# ============================================================
# 第四部分：SiliconFlow bge-m3 embedding
# ============================================================
def embed_batch(texts, retries=3):
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"}
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{SILICONFLOW_BASE_URL}/embeddings",
                headers=headers, json=payload, timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"embedding调用失败（已重试{retries}次）：{last_err}")


# ============================================================
# 主流程
# ============================================================
def process_book(book, content_meta_lookup, collection):
    title = book["title"]
    filename = book["filename"]
    language = book.get("language")
    filepath = os.path.join(SOURCE_DIR, filename)

    if not os.path.exists(filepath):
        log(f"跳过《{title}》：原文件未找到 {filepath}")
        return False

    book_meta = content_meta_lookup.get(title)
    if book_meta is None:
        log(f"跳过《{title}》：metadata.json中无对应内容判断记录")
        return False

    try:
        blocks = extract_blocks(filepath)
    except Exception as e:
        log(f"《{title}》文本提取失败：{e}\n{traceback.format_exc()}")
        return False

    blocks = filter_short_blocks(blocks)
    blocks = filter_noise_blocks(blocks)
    if not blocks:
        log(f"《{title}》过滤后没有剩余内容，跳过")
        return False

    chunks = build_chunks(blocks)
    chunks = add_overlap(chunks)

    ids, documents, metadatas = [], [], []
    for idx, c in enumerate(chunks):
        fields = get_fields_for_chunk(book_meta, c["page_num"])
        chunk_id = f"{title}::{idx}"
        meta = {
            "title": title,
            "language": language,
            "chunk_index": idx,
            "page_num": c["page_num"] if c["page_num"] is not None else -1,
            "chapter_title": fields["chapter_title"] or "",
            "stance": fields["stance"] or "",
            "subfield": fields["subfield"] or ["未标注"],
            "period": fields["period"] or "",
            "region": fields["region"] or ["不涉及地区"],
            "source_type": fields["source_type"] or "",
        }
        ids.append(chunk_id)
        documents.append(c["text"])
        metadatas.append(meta)

    # 分批embedding + 写入
    for start in range(0, len(documents), EMBED_BATCH_SIZE):
        end = start + EMBED_BATCH_SIZE
        batch_docs = documents[start:end]
        try:
            embeddings = embed_batch(batch_docs)
        except Exception as e:
            log(f"《{title}》第{start}-{end}批embedding失败：{e}")
            _cleanup_partial(collection, title, ids[:start])
            return False
        try:
            collection.add(
                ids=ids[start:end],
                documents=batch_docs,
                embeddings=embeddings,
                metadatas=metadatas[start:end],
            )
        except Exception as e:
            log(f"《{title}》第{start}-{end}批写入ChromaDB失败：{e}")
            _cleanup_partial(collection, title, ids[:start])
            return False

    log(f"《{title}》完成：{len(chunks)}个chunk已写入")
    return True


def _cleanup_partial(collection, title, written_ids):
    """某本书处理到一半失败时，把已经写进去的部分chunk删掉，避免下次重跑时残留不完整数据或撞id"""
    if not written_ids:
        return
    try:
        collection.delete(ids=written_ids)
        log(f"  已清理《{title}》此前写入的{len(written_ids)}个不完整chunk")
    except Exception as e:
        log(f"  清理《{title}》不完整chunk时出错：{e}（请手动检查该书在库中的残留数据）")


def main():
    with open(BOOKDATA_PATH, encoding="utf-8") as f:
        bookdata = json.load(f)
    content_meta_lookup = load_content_metadata()

    collection = get_collection()   # 由 config.BACKEND 决定走本地还是 Zilliz

    processed = load_processed()
    total = len(bookdata)
    done = 0

    for book in bookdata:
        title = book["title"]
        if title in processed:
            done += 1
            continue

        log(f"开始处理（{done + 1}/{total}）：{title}")
        try:
            ok = process_book(book, content_meta_lookup, collection)
        except Exception as e:
            log(f"《{title}》处理时发生未捕获异常：{e}\n{traceback.format_exc()}")
            ok = False

        # 只有成功的书才标记已处理；失败的书不标记，下次重跑会自动重试
        # （process_book内部失败时已清理该书写入的部分chunk，重跑不会产生重复id）
        if ok:
            mark_processed(title)
        else:
            log(f"《{title}》未标记为已完成，下次运行会自动重试")
        done += 1

    log(f"全部处理完毕：{done}/{total}")
    log(f"当前collection总片段数：{collection.count()}")


if __name__ == "__main__":
    main()