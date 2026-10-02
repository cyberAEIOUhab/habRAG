"""
ingest_new.py —— 2026-09 批次入库脚本（ÖUA / MRP / Conrad / 新增专著）

设计要点（依预抽样测试结论）：
- 两套切分制度并存：
    · 文档级切分（ÖUA、MRP）：块首 Nr. 标记为唯一依据，文档内 overlap，文档间硬边界
    · 词数切分（Conrad、专著）：沿用 ingest.py 既有规则
- 每块可带文件头前缀 [卷 · 文件号 · 日期]
- 断词修复分材料处理：
    · ÖUA 用保守规则（仅当连字符后接小写字母才合并），保护 Oesterreich-Ungarn 这类复合词
    · Conrad 用 ¬（U+00AC）删除，零风险
- 支持断点续跑（按 title 记录于 ingest_new_processed.txt）

用法：
    python -X utf8 ingest_new.py --only <group>      # group ∈ oua|mrp|conrad|books
    python -X utf8 ingest_new.py --limit-books 1     # 只跑前 N 本（试跑）
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from collections import Counter

import fitz
import requests
import chromadb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, EMBEDDING_MODEL, CHROMA_DB_PATH,
)
# ★ 统一从 corpus_lib 取 collection：它按 config.BACKEND 分派（chroma 本地 / zilliz 云端）。
#   不要在这里自建 chromadb.PersistentClient，那会绕过后端开关。
from corpus_lib import get_collection

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKDATA_PATH = os.path.join(PROJECT_DIR, "bookdata.json")
METADATA_PATH = os.path.join(PROJECT_DIR, "metadata.json")
SOURCE_DIR = r"D:\哈布斯堡史"
MRP_TEI_DIR = os.path.join(
    r"C:\Users\notch\Desktop",
    "oeaw-ministerratsprotokolle-mp-edition-data-4f261cb", "TEI")
LOG_PATH = os.path.join(PROJECT_DIR, "ingest_new_log.txt")
PROCESSED_PATH = os.path.join(PROJECT_DIR, "ingest_new_processed.txt")

COLLECTION_NAME = "habsburg"
EMBED_BATCH_SIZE = 16

# ---- 切分参数 ----
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+|[\u4e00-\u9fff]")
SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s*")
DOC_CAP = 800          # 文档级切分的单块词数上限
DOC_OVERLAP = 75       # 文档内块间 overlap
MIN_DOC_WORDS = 20     # 低于此词数的"文档"视为误检，丢弃
BOOK_MERGE = 100       # 专著切分（沿用 ingest.py）
BOOK_CAP = 500
BOOK_OVERLAP = 75

# ---- 断词 ----
SHY = "\u00ac"                                        # Conrad 软连字符
HYPH_LOWER = re.compile(r"([A-Za-zÀ-ÿ])-\s*\n\s*([a-zà-ÿ])")   # ÖUA 保守规则

# ---- ÖUA 边界检测 ----
MONTHS = (r"Januar|J(?:ä|a)nner|Februar|M(?:ä|a)rz|April|Juni|Juli|August|September|"
          r"Oktober|November|Dezember|Sept|Okt|Nov|Dez|Jan|J(?:ä|a)n|Feb|M(?:ä|a)r|"
          r"Apr|Mai|Jun|Jul|Aug|Sep")
MON_RE = re.compile(MONTHS, re.I)
DATE_RE = re.compile(
    r"(?<![0-9lI|])([0-9lI|]{1,2})\s*[.\-—]?\s*(?:([0-9lI|]{1,2})\s*[.\-—]?\s*)?("
    + MONTHS + r")\s*\.?\s*([0-9lI|]{4})", re.I)
MON_MAP = {"jan": "01", "jän": "01", "feb": "02", "mär": "03", "mar": "03", "apr": "04",
           "mai": "05", "jun": "06", "jul": "07", "aug": "08", "sep": "09", "okt": "10",
           "nov": "11", "dez": "12"}
DIGIT_TR = str.maketrans({"l": "1", "I": "1", "|": "1", "\u00b0": "0"})
DOC_START = re.compile(r"^\s*Nr\s*\.?\s*([0-9lI|\u00b0]{3,6})")
HEAD_START = re.compile(r"^Nr\s*\.?\s*[0-9lI|\u00b0]")
BEILAGE = re.compile(r"^\s*Beilage\s+(?:zu|zum)\s+(?:n\.?\s*)?(\d{3,5})", re.I)


# ============================================================
# 基础设施
# ============================================================
def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_processed():
    if not os.path.exists(PROCESSED_PATH):
        return set()
    with open(PROCESSED_PATH, encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())


def mark_processed(title):
    with open(PROCESSED_PATH, "a", encoding="utf-8") as f:
        f.write(title + "\n")


def count_words(t):
    return len(WORD_RE.findall(t))


def embed_batch(texts, retries=4):
    headers = {"Authorization": "Bearer " + SILICONFLOW_API_KEY,
               "Content-Type": "application/json"}
    payload = {"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"}
    last = None
    for a in range(retries):
        try:
            r = requests.post(SILICONFLOW_BASE_URL + "/embeddings",
                              headers=headers, json=payload, timeout=90)
            if r.status_code == 429:
                time.sleep(2 ** a * 2)
                continue
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except Exception as e:
            last = e
            time.sleep(2 ** a)
    raise RuntimeError("embedding 失败（重试 %d 次）：%s" % (retries, last))


def split_by_words(text, cap, overlap=0, sentence_aware=True):
    """按词数上限切分；sentence_aware 时尽量在句末切开。"""
    if count_words(text) <= cap:
        return [text]
    if sentence_aware:
        sents = [s for s in SENT_SPLIT.split(text) if s.strip()]
    else:
        sents = [text]
    out, cur = [], ""
    for s in sents:
        cand = (cur + " " + s).strip() if cur else s
        if count_words(cand) > cap and cur:
            out.append(cur)
            if overlap:
                tail = " ".join(WORD_RE.findall(cur)[-overlap:])
                cur = (tail + " " + s).strip()
            else:
                cur = s
        else:
            cur = cand
    if cur.strip():
        out.append(cur.strip())
    # 兜底：仍有超长的（无句末标点）按词硬切
    final = []
    for c in out:
        if count_words(c) <= cap:
            final.append(c)
        else:
            pos = [m.start() for m in WORD_RE.finditer(c)]
            st = 0
            while st < len(pos):
                en = min(st + cap, len(pos))
                final.append(c[pos[st]: pos[en] if en < len(pos) else len(c)])
                if en >= len(pos):
                    break
                st = en - overlap if overlap else en
    return [f for f in final if f.strip()]


# ============================================================
# ChromaDB 写入
# ============================================================
def make_meta(title, language, idx, text, entry_meta, page_num=-1,
              chapter_title="", doc_number=None, doc_date=None,
              doc_part=None, doc_section=None):
    sub = entry_meta.get("subfield") or ["未标注"]
    reg = entry_meta.get("region") or ["不涉及地区"]
    m = {
        "title": title,
        "language": language or "未知",
        "chunk_index": int(idx),
        "page_num": int(page_num) if page_num is not None else -1,
        "chapter_title": chapter_title or "",
        "stance": entry_meta.get("stance") or "",
        "subfield": [str(x) for x in sub],
        "period": entry_meta.get("period") or "",
        "region": [str(x) for x in reg],
        "source_type": entry_meta.get("source_type") or "",
    }
    if doc_number:
        m["doc_number"] = str(doc_number)
    if doc_date:
        m["doc_date"] = str(doc_date)
    if doc_part is not None:
        m["doc_part"] = int(doc_part)
    if doc_section:
        m["doc_section"] = str(doc_section)
    return m


def write_chunks(entry, chunks, collection):
    """chunks: list of (text, page_num, chapter_title, doc_number, doc_date, doc_part, doc_section)"""
    title = entry["title"]
    language = entry.get("language")
    meta = entry["_meta"]
    # 幂等：先删除该书已有 chunk
    try:
        collection.delete(where={"title": title})
    except Exception:
        pass
    ids, docs, metas, embs = [], [], [], []
    for i, c in enumerate(chunks):
        text, page, chap, dn, dd, dp, ds = c
        ids.append("%s::%d" % (title, i))
        docs.append(text)
        metas.append(make_meta(title, language, i, text, meta, page, chap, dn, dd, dp, ds))
    for s in range(0, len(docs), EMBED_BATCH_SIZE):
        e = min(s + EMBED_BATCH_SIZE, len(docs))
        vec = embed_batch(docs[s:e])
        collection.add(ids=ids[s:e], documents=docs[s:e],
                       embeddings=vec, metadatas=metas[s:e])
    return len(docs)


# ============================================================
# A. ÖUA —— 文档级切分
# ============================================================
def head_date(line):
    """从页眉提取文件日期。只对数字部分做 OCR 归一化，避免破坏 Juli/April 等含 l 的词。"""
    for m in DATE_RE.finditer(line):
        k = m.group(3).lower()
        mm = MON_MAP.get(k[:3])
        if not mm:
            continue
        day = m.group(1).translate(DIGIT_TR)
        yr = m.group(4).translate(DIGIT_TR)
        if not day.isdigit() or not yr.isdigit():
            continue
        d, y = int(day), int(yr)
        if not (1848 <= y <= 1926) or not (1 <= d <= 31):
            continue
        return "%s-%s-%02d" % (y, mm, d)
    return None


def extract_oua(entry):
    """返回 [(text, page, chap, doc_number, doc_date, doc_part, doc_section), ...]"""
    path = os.path.join(SOURCE_DIR, entry["filename"])
    doc = fitz.open(path)
    docs = []          # [num, date, section, page, [texts]]
    cur = None
    seen = set()
    for i in range(doc.page_count):
        blocks = sorted(doc[i].get_text("blocks"), key=lambda b: (round(b[1] / 3), b[0]))
        page_head = ""
        if blocks:
            f = blocks[0][4].strip()
            if HEAD_START.match(f) and len(f) < 130:
                page_head = f
        for b in blocks:
            t = b[4].strip()
            if not t:
                continue
            beil = BEILAGE.match(t)
            m = DOC_START.match(t)
            if beil:
                # 附件：独立成块，继承父号
                if cur:
                    docs.append(cur)
                cur = [beil.group(1).translate(DIGIT_TR), head_date(page_head) or head_date(t),
                       "Beilage", i + 1, [t]]
                continue
            num = None
            if m:
                s = m.group(1).translate(DIGIT_TR)
                if s.isdigit() and 3 <= len(s) <= 5 and s not in seen:
                    num = s
            if num:
                seen.add(num)
                if cur:
                    docs.append(cur)
                cur = [num, head_date(page_head) or head_date(t), "", i + 1, [t]]
            elif cur is not None:
                cur[4].append(t)
    if cur:
        docs.append(cur)
    doc.close()

    out = []
    for num, date, sec, page, texts in docs:
        body = "\n".join(texts)
        body = HYPH_LOWER.sub(r"\1\2", body)          # 保守断词修复
        w = count_words(body)
        if w < MIN_DOC_WORDS:
            continue
        parts = split_by_words(body, DOC_CAP, DOC_OVERLAP)
        label = "%s · Nr. %s" % (entry["_band"], num)
        if date:
            label += " · " + date
        if sec:
            label += " · " + sec
        for k, p in enumerate(parts):
            out.append(("[%s]\n%s" % (label, p), page, "", num, date, k,
                        sec))
    return out


# ============================================================
# B. MRP —— TEI protocol 级切分
# ============================================================
T = "{http://www.tei-c.org/ns/1.0}"
MRP_FILE = re.compile(r"^MRP-(\d)-(\d)-(\d+)-(\d+)-(\d{8})-([A-Z])-(\d+)\.xml$")


def extract_mrp(entry):
    import xml.etree.ElementTree as ET
    import glob
    pattern = os.path.join(MRP_TEI_DIR, entry["filename"])
    files = sorted(glob.glob(pattern))
    out = []
    for fp in files:
        base = os.path.basename(fp)
        m = MRP_FILE.match(base)
        if not m:
            continue
        serie, abt, band, teil, date, typ, num = m.groups()
        if date == "00000000":
            continue
        try:
            root = ET.parse(fp).getroot()
        except Exception:
            continue
        for dv in root.iter(T + "div"):
            if dv.get("type") != "protocol":
                continue
            text = re.sub(r"\s+", " ", " ".join(dv.itertext())).strip()
            if count_words(text) < MIN_DOC_WORDS:
                continue          # 空壳（1927年大火烧毁）跳过
            d = "%s-%s-%s" % (date[:4], date[4:6], date[6:8])
            if serie == "1":
                label = "MRP 1/%s/%d · Nr. %s · %s" % (abt, int(band), num, d)
            else:
                label = "MRP 3/%d%s · Nr. %s · %s" % (
                    int(band), ("/" + teil) if teil != "0" else "", num, d)
            parts = split_by_words(text, DOC_CAP, DOC_OVERLAP)
            for k, p in enumerate(parts):
                out.append(("[%s]\n%s" % (label, p), -1, "", num, d, k, ""))
    return out


# ============================================================
# C. Conrad —— OOeLB Goobi API
# ============================================================
OOELB = "https://digi.landesbibliothek.at/viewer/api/v1/records/%s/pages/%d/text/?format=oa"
OOELB_IDS = {"I": ("AC01669576", 692), "II": ("AC02267346", 489),
             "III": ("AC02267360", 834), "IV": ("AC00840833", 971),
             "V": ("AC02267313", 1021)}


def fetch_ooelb_page(rid, p, retries=3):
    ua = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,*/*"}
    for a in range(retries):
        try:
            r = requests.get(OOELB % (rid, p), headers=ua, timeout=60)
            if r.status_code != 200:
                time.sleep(2 ** a)
                continue
            d = r.json()
            parts = []
            for ann in d.get("resources", []):
                res = ann.get("resource")
                if isinstance(res, dict) and res.get("chars"):
                    parts.append(res["chars"])
            return " ".join(parts)
        except Exception:
            time.sleep(2 ** a)
    return ""


def extract_conrad(entry):
    roman = entry["_roman"]
    rid, npages = OOELB_IDS[roman]
    out = []
    buf, buf_start = [], 1
    for p in range(1, npages + 1):
        t = fetch_ooelb_page(rid, p)
        if not t:
            continue
        t = re.sub(r"\s*" + SHY + r"\s*", "", t)
        buf.append(t)
        if sum(count_words(x) for x in buf) >= BOOK_CAP:
            txt = " ".join(buf)
            for k, part in enumerate(split_by_words(txt, BOOK_CAP, BOOK_OVERLAP)):
                out.append((part, buf_start, "", None, None, None, None))
            buf, buf_start = [], p + 1
    if buf:
        txt = " ".join(buf)
        for k, part in enumerate(split_by_words(txt, BOOK_CAP, BOOK_OVERLAP)):
            out.append((part, buf_start, "", None, None, None, None))
    return out


# ============================================================
# D. 专著 —— 沿用 ingest.py 词数切分
# ============================================================
def extract_pdf(entry):
    path = os.path.join(SOURCE_DIR, entry["filename"])
    doc = fitz.open(path)
    blocks = []
    for i in range(doc.page_count):
        for b in doc[i].get_text("blocks"):
            t = b[4].strip()
            if t:
                blocks.append((t, i + 1))
    doc.close()
    return _blocks_to_chunks(blocks)


def extract_epub(entry):
    import ebooklib
    from ebooklib import epub
    path = os.path.join(SOURCE_DIR, entry["filename"])
    book = epub.read_epub(path)
    tag = re.compile(r"<[^>]+>")
    blocks = []
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        html = item.get_content().decode("utf-8", "ignore")
        txt = tag.sub("\n", html)
        for para in re.split(r"\n{2,}", txt):
            para = para.strip()
            if len(WORD_RE.findall(para)) >= 5:
                blocks.append((para, -1))
    return _blocks_to_chunks(blocks)


def _blocks_to_chunks(blocks):
    short = [b[0] for b in blocks if count_words(b[0]) <= 20]
    noise = {t for t, n in Counter(short).items() if n >= 3}
    blocks = [b for b in blocks if b[0] not in noise]
    chunks, cur, cur_page = [], "", -1
    for t, pg in blocks:
        cand = (cur + "\n" + t) if cur else t
        if count_words(cand) > BOOK_CAP and cur:
            chunks.append((cur, cur_page))
            cur, cur_page = t, pg
        else:
            if not cur:
                cur_page = pg
            cur = cand
            if count_words(cur) >= BOOK_MERGE:
                chunks.append((cur, cur_page))
                cur, cur_page = "", -1
    if cur.strip():
        chunks.append((cur, cur_page))
    out = []
    for txt, pg in chunks:
        for k, part in enumerate(split_by_words(txt, BOOK_CAP, BOOK_OVERLAP)):
            out.append((part, pg, "", None, None, None, None))
    return out


# ============================================================
# 主流程
# ============================================================
def classify(entry):
    t = entry["title"]
    if t.startswith("Österreich-Ungarns Außenpolitik"):
        return "oua"
    if t.startswith("Die Ministerratsprotokolle") or t.startswith("Die Protokolle des cisleithanischen"):
        return "mrp"
    if t.startswith("Aus meiner Dienstzeit"):
        return "conrad"
    return "books"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="oua|mrp|conrad|books")
    ap.add_argument("--limit-books", type=int, default=0)
    args = ap.parse_args()

    bookdata = json.load(open(BOOKDATA_PATH, encoding="utf-8"))
    meta_lookup = {m["title"]: m for m in json.load(open(METADATA_PATH, encoding="utf-8"))}
    col = get_collection()   # 由 config.BACKEND 决定走本地还是 Zilliz
    processed = load_processed()

    NEW = [b for b in bookdata if classify(b) != "books"]
    BOOKS = [b for b in bookdata if classify(b) == "books" and
             b["title"] in {x["title"] for x in bookdata[-56:]}]
    groups = {"oua": [b for b in NEW if classify(b) == "oua"],
              "mrp": [b for b in NEW if classify(b) == "mrp"],
              "conrad": [b for b in NEW if classify(b) == "conrad"],
              "books": BOOKS}
    log("=" * 70)
    log("入库开始：oua=%d mrp=%d conrad=%d books=%d | 库内现有 %d chunks" % (
        len(groups["oua"]), len(groups["mrp"]), len(groups["conrad"]),
        len(groups["books"]), col.count()))

    todo = []
    for g in ("books", "oua", "mrp", "conrad"):
        if args.only and args.only != g:
            continue
        todo += [(g, b) for b in groups[g]]
    if args.limit_books:
        todo = todo[:args.limit_books]

    for g, entry in todo:
        title = entry["title"]
        if title in processed:
            log("跳过（已完成）：%s" % title[:70])
            continue
        t0 = time.time()
        try:
            entry["_meta"] = meta_lookup.get(title, {})
            if g == "oua":
                entry["_band"] = "ÖUA " + title.rsplit(" ", 1)[-1]
                chunks = extract_oua(entry)
            elif g == "mrp":
                chunks = extract_mrp(entry)
            elif g == "conrad":
                entry["_roman"] = title.split("Band ")[1].split(":")[0].strip()
                chunks = extract_conrad(entry)
            else:
                fn = entry["filename"].lower()
                chunks = extract_epub(entry) if fn.endswith(".epub") else extract_pdf(entry)
            if not chunks:
                log("★ %s 无产出，跳过" % title[:70])
                continue
            n = write_chunks(entry, chunks, col)
            mark_processed(title)
            log("完成 %-62s %5d chunks  %.0fs  (库内 %d)" % (
                title[:62], n, time.time() - t0, col.count()))
        except Exception as e:
            log("✗ %s 失败：%s\n%s" % (title[:60], e, traceback.format_exc()[:800]))
    log("全部结束。库内总片段数：%d" % col.count())


if __name__ == "__main__":
    main()
