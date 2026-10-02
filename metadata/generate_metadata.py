#!/usr/bin/env python3
"""
Generate content-level judgment metadata for Habsburg history book collection.
Processes books one at a time with resume capability.
Outputs: metadata.json (results) + metadata_log.txt (progress log)
"""

import fitz  # PyMuPDF
import json
import os
import re
import sys
import io
import time
from datetime import datetime
from collections import Counter

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ── Config ──────────────────────────────────────────────────
# ★ 密钥不再写死在这里：从项目根的 .env 读取（该文件已被 .gitignore 排除）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL  # noqa: E402

DEEPSEEK_MODEL = "deepseek-v4-pro"

BOOKDATA_PATH = r"C:\Users\notch\Desktop\habRAG\bookdata.json"
PDF_DIR = r"C:\Users\notch\Desktop\哈布斯堡史"
METADATA_PATH = r"C:\Users\notch\Desktop\habRAG\metadata.json"
LOG_PATH = r"C:\Users\notch\Desktop\habRAG\metadata_log.txt"

# Rate limiting
CALL_DELAY = 1.0  # seconds between API calls

# ── Front matter keywords to filter ─────────────────────────
FRONT_MATTER_PATTERNS = [
    r'^\s*cover\s*$', r'^\s*front cover\s*$', r'^\s*back\s*cover\s*$',
    r'^\s*backcover\s*$', r'^\s*spine\s*$', r'^\s*title\s*page\s*$',
    r'^\s*title\s*$', r'^\s*half[- ]?title\s*$', r'^\s*titel\s*$',
    r'^\s*copyright\s*$', r'^\s*impressum\s*$',
    r'^\s*contents?\s*$', r'^\s*table of contents\s*$',
    r'^\s*figures\s*$', r'^\s*tables\s*$', r'^\s*maps\s*$',
    r'^\s*contributors\s*$', r'^\s*acknowledg?ments?\s*$',
    r'^\s*abbreviations?\s*$', r'^\s*list of .*$',
    r'^\s*bibliography\s*$', r'^\s*references\s*$',
    r'^\s*index\s*$', r'^\s*glossary\s*$',
    r'^\s*note on .*$', r'^\s*a note on .*$',
    r'^\s*recommended citation\s*$',
    r'^\s*scanned using .*$',
    r'^\s*editorial preface\s*$',
    r'^\s*preface\s*$', r'^\s*foreword\s*$',
    r'^\s*issue table of contents\s*$',
    r'^\s*article contents\s*$',
    r'^\s*front matter\s*$', r'^\s*back matter\s*$',
    r'^\s*noticeboard\s*$',
    r'^\s*place[- ]name equivalents\s*$',
    # German front/back matter
    r'^\s*inhaltsverzeichnis\s*$', r'^\s*literatur\s*$', r'^\s*register\s*$',
    r'^\s*geschichte kompakt\s*$', r'^\s*einf[uü]hrung\s*$',
    # Dedication / colophon / copyright page
    r'^\s*dedication\s*$', r'^\s*copyright page\s*$',
    r'^\s*other books by .*$', r'^\s*also by .*$',
    # Permissions / credits
    r'^\s*permissions acknowledgments?\s*$',
    r'^\s*illustration credits\s*$',
    r'^\s*photo credits\s*$',
    # Footnotes / endnotes (usually backmatter, not content chapters)
    r'^\s*footnotes?\s*$', r'^\s*endnotes?\s*$',
    # About the translator / contributors
    r'^\s*about the translator\s*$',
    r'^\s*notes on the contributors\s*$',
    r'^\s*notes on contributors\s*$',
    # Leaflets / sketches (military history appendices)
    r'^\s*leaflets\s*$', r'^\s*sketches\s*$',
    # Series / imprint pages
    r'^\s*series page\s*$', r'^\s*series title\s*$',
    r'^\s*imprints? page\s*$', r'^\s*landing page\s*$',
    r'^\s*genealogical tables?\s*$',
    r'^\s*epigraph\s*$',
    # Essay on sources / guide to pronunciation
    r'^\s*essay on sources\s*$',
    r'^\s*a guide to .*pronunciation\s*$',
    r'^\s*about the book\s*$',
    # Appendix / Appendices (backmatter, not content chapters)
    r'^\s*appendix \d.*$', r'^\s*appendices\s*$',
    # Glossary
    r'^\s*glossary of .*$',
    # Select bibliography (already have selected, adding select)
    r'^\s*select bibliography\s*$',
    r'^\s*selected printed sources and literature\s*$',
    r'^\s*index of people and places\s*$',
    # Index / backmatter entries
    r'^\s*bibliography\s*$', r'^\s*references\s*$', r'^\s*notes\s*$',
    r'^\s*appendix\s*$', r'^\s*appendices\s*$',
    r'^\s*selected bibliography\s*$',
    r'^\s*about the author\s*$', r'^\s*about the contributors\s*$',
    # Single letter index entries: "A", "B", ..., "Z"
    r'^[A-Za-z]$',
    # Letter range index entries: "A-C", "D-F", "S-Z", etc.
    r'^[A-Za-z]\s*[-–—]\s*[A-Za-z]$',
    # Numeric index: "1-100", etc.
    r'^\d+\s*[-–—]\s*\d+$',
]


def is_front_matter(title):
    """Check if a TOC entry is front/back matter."""
    t = title.strip().lower()
    for pat in FRONT_MATTER_PATTERNS:
        if re.match(pat, t):
            return True
    return False


def is_page_label(title):
    """Detect page-label-style entries (OCR artifacts, page numbers, etc.)."""
    t = title.strip().lower()
    # Patterns like 'Road_A001', 'CBO978...', 'albertini217032019'
    if re.match(r'^[a-z]+[_\-\s]*[a-z]*\d{2,}[a-z]*\d*$', t):
        return True
    # Patterns like 'albertini120072020_1-2' (word + digits + _ + digits + - + digits)
    if re.match(r'^[a-z]+\d+[_\-\s]\d+[_\-\s]\d+$', t):
        return True
    if re.match(r'^[a-z]+\d+[_\-\s]\d+$', t):
        return True
    # Patterns like 'p. [311]', 'p. 312', 'p.311'
    if re.match(r'^p\.?\s*\[?\d+\]?$', t):
        return True
    # Pure numbers
    if re.match(r'^\d+$', t):
        return True
    # "Binder1", "Binder 2", etc.
    if re.match(r'^binder\s*\d*$', t):
        return True
    # Generic OCR artifact: mix of letters+digits+underscores with no readable words
    # e.g., "albertini120072020_1-2", "YPP-24072020_1-2"
    if re.match(r'^[a-z]+[-_\s]?\d{6,}[-_\s]?\d*[-_\s]?\d*$', t):
        return True
    return False


def is_real_chapter(title):
    """A TOC entry is a 'real' chapter if it's neither front matter nor a page label."""
    return not is_front_matter(title) and not is_page_label(title)


def extract_text_sample(doc, start_page, end_page, max_chars=2000):
    """
    Extract representative text from a page range.
    Takes beginning, middle, and end portions.
    start_page, end_page are 0-indexed PDF page numbers.
    """
    total_pages = end_page - start_page + 1
    if total_pages <= 0:
        return ""

    # Pick sample pages: first 2, middle 1-2, last 1-2
    sample_pages = []
    if total_pages <= 3:
        sample_pages = list(range(start_page, end_page + 1))
    else:
        sample_pages = [start_page, start_page + 1]  # beginning
        mid = start_page + total_pages // 2
        sample_pages.append(mid)
        if total_pages > 6:
            sample_pages.append(mid + 1)
        sample_pages.append(end_page - 1)
        sample_pages.append(end_page)

    # Deduplicate and sort
    sample_pages = sorted(set(sample_pages))
    # Ensure within range
    sample_pages = [p for p in sample_pages if start_page <= p <= end_page]

    texts = []
    chars_per_sample = max_chars // len(sample_pages)

    for p in sample_pages[:6]:  # Safety limit
        try:
            page = doc[p]
            text = page.get_text()
            # Clean excessive whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > chars_per_sample:
                # Take beginning portion
                text = text[:chars_per_sample]
            if text:
                texts.append(text)
        except Exception:
            pass

    return '\n\n---\n\n'.join(texts)


def _build_chapter_list(entries):
    """Build chapter list with page ranges from TOC entries."""
    chapters = []
    for i, entry in enumerate(entries):
        title = entry[1].strip()
        # Clean HTML entities
        title = title.replace('&#8211;', '–').replace('&#8212;', '—').replace('&amp;', '&')
        title = re.sub(r'&#\d+;', '', title)
        title = re.sub(r'\s+', ' ', title).strip()

        start_page = entry[2]
        end_page = None  # will be set later
        chapters.append({
            'chapter_title': title,
            'start_page': start_page,
            'end_page': None,
            '_idx': i,
        })

    # Set end pages
    for i, ch in enumerate(chapters):
        if i < len(chapters) - 1:
            ch['end_page'] = chapters[i + 1]['start_page'] - 1
        else:
            ch['end_page'] = 999999  # clamped to doc page count later
        del ch['_idx']

    return chapters


def analyze_toc(toc):
    """
    Analyze a PDF TOC to determine if it has real chapter structure.
    Returns: (granularity, chapter_list) where chapter_list is
    [(title, start_page, end_page), ...] or None for book-level.
    """
    if not toc:
        return 'book', None

    # Count entries by level
    level_counts = Counter(t[0] for t in toc)
    max_level = max(level_counts.keys()) if level_counts else 0

    # For each level, count "real" entries
    # Strategy: prefer level 1 if it has >= 2 real chapters.
    # Only fall back to deeper levels if level 1 is clearly not real content.
    level_data = {}
    for lvl in sorted(level_counts.keys()):
        entries = [t for t in toc if t[0] == lvl]
        real = [t for t in entries if is_real_chapter(t[1])]
        page_labels = sum(1 for t in entries if is_page_label(t[1]))
        real_ratio = len(real) / len(entries) if entries else 0
        page_label_ratio = page_labels / len(entries) if entries else 0

        level_data[lvl] = {
            'real': real,
            'count': len(real),
            'total': len(entries),
            'real_ratio': real_ratio,
            'page_label_ratio': page_label_ratio,
        }

    # If level 1 has >= 2 real chapters AND real entries are majority, use level 1
    l1 = level_data.get(1, {})
    if l1.get('count', 0) >= 2 and l1.get('real_ratio', 0) >= 0.4:
        return 'chapter', _build_chapter_list(l1['real'])

    # Otherwise, find the best level that:
    # - Has >= 2 real entries
    # - Is NOT majority page labels
    # - Has a decent real_ratio (> 30%)
    best_level = None
    best_real_entries = None
    best_count = 0

    for lvl, ld in sorted(level_data.items()):
        if ld['count'] < 2:
            continue
        if ld['page_label_ratio'] > 0.5:
            continue
        if ld['real_ratio'] < 0.3:
            continue
        # Prefer shallower levels; break ties with count
        if best_level is None or lvl < best_level or (lvl == best_level and ld['count'] > best_count):
            best_level = lvl
            best_real_entries = ld['real']
            best_count = ld['count']

    if best_real_entries is None or len(best_real_entries) < 2:
        return 'book', None

    return 'chapter', _build_chapter_list(best_real_entries)


def call_deepseek(prompt, max_retries=3):
    """Call DeepSeek API with retry logic. Returns parsed JSON or None."""
    import requests

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You are a historian specializing in the Habsburg Empire. You output ONLY valid JSON, no other text."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{DEEPSEEK_API_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Extract JSON from possible markdown code blocks
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
                # Try to find JSON object
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    content = json_match.group(0)
                return json.loads(content)
            elif resp.status_code == 429:
                wait = min(60, 2 ** attempt)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  API error {resp.status_code}: {resp.text[:200]}")
                time.sleep(2 ** attempt)
        except requests.exceptions.Timeout:
            print(f"  Timeout (attempt {attempt + 1})")
            time.sleep(5)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(2 ** attempt)

    return None


# ── Prompt builders ─────────────────────────────────────────

def build_book_level_prompt(description, text_sample):
    """Prompt for combined stance + subfield + period + region + source_type."""
    return f"""Analyze this book about Habsburg/Austro-Hungarian history.

BOOK DESCRIPTION:
{description[:1500]}

REPRESENTATIVE TEXT SAMPLE:
{text_sample[:2000]}

Output a JSON object with these EXACT fields (no other text):

1. "stance": ONE of — "衰落论" / "修正主义" / "中立描述" / "不涉及该争论"
   - 衰落论 = argues empire's collapse was structurally inevitable
   - 修正主义 = emphasizes institutional resilience, critiques decline thesis
   - 中立描述 = neutral/descriptive, doesn't engage the debate
   - 不涉及该争论 = purely archival/technical, not about empire's survival

2. "subfield": array from — "政治史" "外交史" "经济史" "军事史" "社会史" "民族史" "地区研究" "犹太史"

3. "period": string — "YYYY-YYYY" or "YYYY" (MUST be this format, estimate if needed)

4. "region": array from this EXACT list:
   全帝国
   下奥地利, 上奥地利, 萨尔茨堡, 施泰尔马克, 克恩顿, 克赖恩, 蒂罗尔-福拉尔贝格, 滨海地区, 波希米亚, 摩拉维亚, 奥属西里西亚, 加利西亚, 布科维纳, 达尔马提亚
   匈牙利本土, 特兰西瓦尼亚, 克罗地亚-斯拉沃尼亚, 斯洛伐克地区, 伏伊伏丁那/巴纳特, 阜姆
   波斯尼亚-黑塞哥维那
   德意志地区, 巴尔干地区, 奥斯曼帝国, 俄罗斯帝国, 意大利, 波兰

5. "source_type": ONE of — "primary" / "secondary" / "mixed"

Output ONLY the JSON object, nothing else:"""


def build_chapter_level_prompt(chapter_title, text_sample, book_description):
    """Prompt for chapter-level subfield/period/region/source_type."""
    return f"""Analyze this CHAPTER from a book about Habsburg/Austro-Hungarian history.

BOOK CONTEXT:
{book_description[:800]}

CHAPTER TITLE: {chapter_title}

CHAPTER TEXT SAMPLE:
{text_sample[:2000]}

Output a JSON object with these EXACT fields (no other text):

1. "subfield": array from — "政治史" "外交史" "经济史" "军事史" "社会史" "民族史" "地区研究" "犹太史"

2. "period": string — "YYYY-YYYY" or "YYYY" (MUST be this format)

3. "region": array from this EXACT list:
   全帝国
   下奥地利, 上奥地利, 萨尔茨堡, 施泰尔马克, 克恩顿, 克赖恩, 蒂罗尔-福拉尔贝格, 滨海地区, 波希米亚, 摩拉维亚, 奥属西里西亚, 加利西亚, 布科维纳, 达尔马提亚
   匈牙利本土, 特兰西瓦尼亚, 克罗地亚-斯拉沃尼亚, 斯洛伐克地区, 伏伊伏丁那/巴纳特, 阜姆
   波斯尼亚-黑塞哥维那
   德意志地区, 巴尔干地区, 奥斯曼帝国, 俄罗斯帝国, 意大利, 波兰

4. "source_type": ONE of — "primary" / "secondary" / "mixed"

Output ONLY the JSON object, nothing else:"""


def build_stance_prompt(description, text_sample):
    """Prompt for stance-only judgment (for chapter-level books)."""
    return f"""Analyze this book about Habsburg/Austro-Hungarian history.

BOOK DESCRIPTION:
{description[:1500]}

REPRESENTATIVE TEXT SAMPLE:
{text_sample[:2000]}

What is the book's stance on the Habsburg Empire's decline/fate?

Output a JSON object with ONE field:

"stance": ONE of — "衰落论" / "修正主义" / "中立描述" / "不涉及该争论"
   - 衰落论 = argues empire's collapse was structurally inevitable, structural weaknesses destined it to fail
   - 修正主义 = emphasizes institutional resilience, day-to-day workings, critiques the teleological decline narrative
   - 中立描述 = neutral/descriptive, doesn't actively take sides in the historiographical debate
   - 不涉及该争论 = purely archival document collection, technical military/economic history, etc. that doesn't touch on the empire's survival question

Output ONLY the JSON object:"""


# ── Main processing ─────────────────────────────────────────

def load_completed_titles():
    """Load list of already-completed book titles from log file."""
    if not os.path.exists(LOG_PATH):
        return set()
    completed = set()
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            if '| DONE |' in line or '| DONE' in line:
                parts = line.split('|')
                if parts:
                    completed.add(parts[0].strip())
    return completed


def log_result(title, granularity, chapter_count, status):
    """Append a result line to the log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{title} | {granularity} | {chapter_count} | {status} | {timestamp}\n"
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line)


def append_metadata(entry):
    """Append a book result to metadata.json (handles JSON array format)."""
    if not os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, 'w', encoding='utf-8') as f:
            f.write('[\n')
        existing = []
    else:
        with open(METADATA_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        # Parse existing array
        try:
            existing = json.loads(content)
        except json.JSONDecodeError:
            print("  WARNING: metadata.json corrupt, starting fresh")
            existing = []

    existing.append(entry)

    with open(METADATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def process_book(book_data):
    """Process a single book. Returns the metadata entry or None on failure."""
    title = book_data['title']
    description = book_data.get('description', '')
    filename = book_data['filename']
    pdf_path = os.path.join(PDF_DIR, filename)

    print(f"\n{'='*60}")
    print(f"Processing: {title[:80]}")

    # Check if PDF exists
    if not os.path.exists(pdf_path):
        # Try case-insensitive match
        pdf_dir_files = os.listdir(PDF_DIR)
        match = None
        for f in pdf_dir_files:
            if f.lower() == filename.lower():
                match = f
                break
        if match:
            pdf_path = os.path.join(PDF_DIR, match)
        else:
            print(f"  ERROR: PDF not found: {filename}")
            return None

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  ERROR opening PDF: {e}")
        return None

    total_pages = doc.page_count

    # Get TOC
    toc = doc.get_toc()

    # Analyze TOC for chapter structure
    granularity, chapters = analyze_toc(toc)

    # For chapter-level books, clamp end_pages
    if chapters:
        for ch in chapters:
            if ch['end_page'] is None or ch['end_page'] > total_pages - 1:
                ch['end_page'] = total_pages - 1
            # Ensure start_page is valid
            ch['start_page'] = max(0, min(ch['start_page'], total_pages - 1))
            ch['end_page'] = max(ch['start_page'], min(ch['end_page'], total_pages - 1))

    # Extract book-level text sample (beginning, middle, end)
    # Book-level: 3 sample points across the book
    book_sample_pages = []
    if total_pages <= 3:
        book_sample_pages = list(range(total_pages))
    else:
        third = total_pages // 3
        book_sample_pages = [0, 1, third, third + 1, 2 * third, 2 * third + 1, total_pages - 2, total_pages - 1]
    book_sample_pages = sorted(set(p for p in book_sample_pages if 0 <= p < total_pages))[:8]

    book_text_sample = ""
    for p in book_sample_pages:
        try:
            text = doc[p].get_text()
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                book_text_sample += text[:500] + "\n\n---\n\n"
        except Exception:
            pass
    book_text_sample = book_text_sample[:3000]

    if granularity == 'chapter' and chapters:
        # ── Chapter-level processing ──
        print(f"  Mode: chapter-level ({len(chapters)} chapters)")

        # Step 1: Book-level stance
        print(f"  Getting stance...")
        stance_prompt = build_stance_prompt(description, book_text_sample)
        stance_result = call_deepseek(stance_prompt)
        time.sleep(CALL_DELAY)

        if stance_result:
            stance = stance_result.get('stance', '中立描述')
            print(f"  Stance: {stance}")
        else:
            stance = '中立描述'
            print(f"  Stance FAILED, defaulting to 中立描述")

        # Step 2: Per-chapter subfield/period/region/source_type
        chapter_results = []
        for i, ch in enumerate(chapters):
            ch_title = ch['chapter_title']
            print(f"  Chapter [{i+1}/{len(chapters)}]: {ch_title[:60]}...")

            # Extract chapter text sample
            ch_text = extract_text_sample(doc, ch['start_page'], ch['end_page'], max_chars=2000)

            ch_prompt = build_chapter_level_prompt(ch_title, ch_text, description)
            ch_result = call_deepseek(ch_prompt)
            time.sleep(CALL_DELAY)

            chapter_entry = {
                "chapter_title": ch_title,
                "start_page": ch['start_page'],
                "end_page": ch['end_page'],
                "subfield": ch_result.get('subfield', ['政治史']) if ch_result else ['政治史'],
                "period": ch_result.get('period', '1867-1918') if ch_result else '1867-1918',
                "region": ch_result.get('region', ['全帝国']) if ch_result else ['全帝国'],
                "source_type": ch_result.get('source_type', 'secondary') if ch_result else 'secondary',
            }
            chapter_results.append(chapter_entry)

        doc.close()

        entry = {
            "title": title,
            "stance": stance,
            "granularity": "chapter",
            "chapters": chapter_results,
        }
        return entry, 'chapter', len(chapter_results)

    else:
        # ── Book-level processing ──
        print(f"  Mode: book-level (no usable chapter structure)")

        prompt = build_book_level_prompt(description, book_text_sample)
        result = call_deepseek(prompt)
        time.sleep(CALL_DELAY)

        doc.close()

        if result:
            entry = {
                "title": title,
                "stance": result.get('stance', '中立描述'),
                "granularity": "book",
                "subfield": result.get('subfield', ['政治史']),
                "period": result.get('period', '1867-1918'),
                "region": result.get('region', ['全帝国']),
                "source_type": result.get('source_type', 'secondary'),
            }
            print(f"  Stance: {entry['stance']}, Period: {entry['period']}, Region: {entry['region']}")
        else:
            # Fallback
            entry = {
                "title": title,
                "stance": "中立描述",
                "granularity": "book",
                "subfield": ["政治史"],
                "period": "1867-1918",
                "region": ["全帝国"],
                "source_type": "secondary",
            }
            print(f"  API FAILED, using fallback values")

        return entry, 'book', 0


def main():
    print("=" * 60)
    print("Habsburg Metadata Generator")
    print(f"Start time: {datetime.now()}")
    print("=" * 60)

    # Load bookdata
    with open(BOOKDATA_PATH, 'r', encoding='utf-8') as f:
        all_books = json.load(f)

    print(f"Total books in bookdata.json: {len(all_books)}")

    # Load completed titles
    completed = load_completed_titles()
    print(f"Already completed: {len(completed)}")

    # Filter to pending books
    pending = [b for b in all_books if b['title'] not in completed]
    print(f"Pending: {len(pending)}")

    if not pending:
        print("All books already processed!")
        return

    # Write log header if new
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(f"# Habsburg Metadata Generation Log\n")
            f.write(f"# Started: {datetime.now()}\n")
            f.write(f"# Total books: {len(all_books)}\n")
            f.write(f"# title | granularity | chapter_count | status | timestamp\n")
            f.write(f"# {'='*80}\n")

    # Process books
    stats = {'chapter': 0, 'book': 0, 'failed': 0}
    max_books = min(len(pending), 50)  # Safety limit per session

    for i, book in enumerate(pending[:max_books]):
        print(f"\n[{i+1}/{max_books} in this session, {len(completed)+i+1}/{len(all_books)} total]")

        try:
            result = process_book(book)
            if result is None:
                log_result(book['title'], 'N/A', 0, 'FAILED')
                stats['failed'] += 1
                continue

            entry, granularity, chapter_count = result
            append_metadata(entry)
            log_result(book['title'], granularity, chapter_count, 'DONE')
            completed.add(book['title'])

            if granularity == 'chapter':
                stats['chapter'] += 1
            else:
                stats['book'] += 1

        except Exception as e:
            print(f"  UNEXPECTED ERROR: {e}")
            import traceback
            traceback.print_exc()
            log_result(book['title'], 'N/A', 0, 'FAILED')
            stats['failed'] += 1

    # Print session summary
    print(f"\n{'='*60}")
    print(f"Session Summary:")
    print(f"  Chapter-level books processed: {stats['chapter']}")
    print(f"  Book-level books processed: {stats['book']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Total completed so far: {len(completed)}/{len(all_books)}")
    print(f"End time: {datetime.now()}")


if __name__ == '__main__':
    main()
