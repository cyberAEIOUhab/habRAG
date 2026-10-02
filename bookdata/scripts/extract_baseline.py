"""
Batch extraction script for Habsburg book collection.
Extracts first-page text, TOC/bookmarks, page count from all files.
Outputs to baseline_extract.json for use in subsequent web-search processing.
"""
import os, sys, json, re
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

SRC_DIR = r'C:\Users\notch\Desktop\哈布斯堡史'
OUT_DIR = r'D:\habsburgRAG'
BASELINE_PATH = os.path.join(OUT_DIR, 'baseline_extract.json')

# --- PDF extraction ---
def process_pdf(filepath):
    """Extract first 3 pages text, TOC, page count from PDF."""
    import fitz  # PyMuPDF
    result = {
        'first_pages_text': '',
        'toc': [],
        'page_count': 0,
        'is_scanned': None,
        'has_bookmarks': False,
        'bookmark_titles': [],
        'error': None
    }
    try:
        doc = fitz.open(filepath)
        result['page_count'] = doc.page_count

        # Extract TOC
        toc = doc.get_toc()
        if toc:
            result['has_bookmarks'] = True
            result['bookmark_titles'] = [
                {'level': item[0], 'title': item[1], 'page': item[2]}
                for item in toc
            ]
            result['toc'] = result['bookmark_titles']
        else:
            result['has_bookmarks'] = False

        # Extract text from first 3 pages (or fewer if doc is shorter)
        pages_to_read = min(3, doc.page_count)
        texts = []
        total_chars = 0
        for i in range(pages_to_read):
            page = doc[i]
            text = page.get_text()
            texts.append(f'--- PAGE {i+1} ---\n{text}')
            total_chars += len(text.strip())

        result['first_pages_text'] = '\n'.join(texts)

        # Heuristic: if first 3 pages have very little text (< 100 chars total),
        # it's likely a scanned document
        if total_chars < 100:
            result['is_scanned'] = True
        elif total_chars < 500:
            result['is_scanned'] = 'likely'
        else:
            result['is_scanned'] = False

        doc.close()
    except Exception as e:
        result['error'] = str(e)

    return result


# --- EPUB extraction ---
def process_epub(filepath):
    """Extract title page content and TOC from EPUB."""
    from ebooklib import epub
    from bs4 import BeautifulSoup

    result = {
        'first_pages_text': '',
        'toc': [],
        'page_count': 0,
        'is_scanned': False,  # EPUBs are digital-native
        'has_bookmarks': None,  # null for non-PDF per spec
        'bookmark_titles': None,
        'error': None
    }
    try:
        book = epub.read_epub(filepath)

        # Get TOC
        toc_items = []
        for item in book.toc:
            if isinstance(item, tuple):
                # (section, [subsections])
                toc_items.append(_parse_epub_toc(item))
            elif isinstance(item, epub.Link):
                toc_items.append({'level': 1, 'title': item.title, 'href': item.href})

        result['toc'] = toc_items

        # Extract text from first few documents
        texts = []
        total_chars = 0
        docs_processed = 0

        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT and docs_processed < 5:
                try:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    # Remove script/style tags
                    for tag in soup(['script', 'style']):
                        tag.decompose()
                    text = soup.get_text()
                    cleaned = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
                    if cleaned:
                        texts.append(cleaned)
                        total_chars += len(cleaned)
                        docs_processed += 1
                except:
                    pass

        result['first_pages_text'] = '\n\n--- NEXT DOC ---\n\n'.join(texts[:3])

    except Exception as e:
        result['error'] = str(e)

    return result


def _parse_epub_toc(item, level=1):
    """Recursively parse EPUB TOC tuples."""
    from ebooklib import epub
    results = []
    if isinstance(item, tuple):
        section, children = item
        if isinstance(section, epub.Link):
            results.append({'level': level, 'title': section.title, 'href': section.href})
        for child in children:
            results.extend(_parse_epub_toc(child, level + 1))
    elif isinstance(item, epub.Link):
        results.append({'level': level, 'title': item.title, 'href': item.href})
    return results


# --- DOCX extraction ---
def process_docx(filepath):
    """Extract first paragraphs from DOCX."""
    from docx import Document
    result = {
        'first_pages_text': '',
        'toc': [],
        'page_count': 0,
        'is_scanned': False,
        'has_bookmarks': None,
        'bookmark_titles': None,
        'error': None
    }
    try:
        doc = Document(filepath)
        paragraphs = []
        total_chars = 0
        for i, para in enumerate(doc.paragraphs):
            if i >= 50:  # First ~50 paragraphs ≈ first few pages
                break
            text = para.text.strip()
            if text:
                paragraphs.append(text)
                total_chars += len(text)

        result['first_pages_text'] = '\n'.join(paragraphs)

    except Exception as e:
        result['error'] = str(e)

    return result


# --- Main processing ---
def main():
    files = sorted([
        f for f in os.listdir(SRC_DIR)
        if os.path.isfile(os.path.join(SRC_DIR, f))
    ])

    # Load existing baseline if resuming
    existing = {}
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
            existing_list = json.load(f)
            for item in existing_list:
                existing[item['filename']] = item
        print(f"Resuming: {len(existing)} files already processed")

    results = []
    total = len(files)
    for i, filename in enumerate(files):
        if filename in existing:
            results.append(existing[filename])
            print(f"[{i+1:03d}/{total}] SKIP (cached): {filename[:80]}")
            continue

        filepath = os.path.join(SRC_DIR, filename)
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        print(f"[{i+1:03d}/{total}] Processing: {filename[:80]}...", end=' ', flush=True)

        base_data = {
            'filename': filename,
            'filepath': filepath,
            'extension': ext,
            'file_size_mb': round(os.path.getsize(filepath) / (1024 * 1024), 2),
        }

        if ext == '.pdf':
            extracted = process_pdf(filepath)
        elif ext == '.epub':
            extracted = process_epub(filepath)
        elif ext == '.docx':
            extracted = process_docx(filepath)
        else:
            extracted = {'error': f'Unsupported format: {ext}'}

        base_data.update(extracted)
        results.append(base_data)

        status = 'ERROR' if extracted.get('error') else 'OK'
        pages = extracted.get('page_count', 0)
        scanned = extracted.get('is_scanned', 'N/A')
        toc_count = len(extracted.get('bookmark_titles') or []) if extracted.get('has_bookmarks') else 0
        print(f"{status} | pages={pages} | scanned={scanned} | bookmarks={toc_count}")

        # Save after every 5 files
        if (i + 1) % 5 == 0:
            with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  [checkpoint: {i+1}/{total} saved]")

    # Final save
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Summary stats
    pdfs = [r for r in results if r['extension'] == '.pdf']
    epubs = [r for r in results if r['extension'] == '.epub']
    docxs = [r for r in results if r['extension'] == '.docx']

    print(f"\n=== EXTRACTION COMPLETE ===")
    print(f"Total: {len(results)}")
    print(f"  PDF: {len(pdfs)} (with bookmarks: {sum(1 for p in pdfs if p.get('has_bookmarks'))})")
    print(f"  EPUB: {len(epubs)}")
    print(f"  DOCX: {len(docxs)}")
    print(f"  Scanned: {sum(1 for r in pdfs if r.get('is_scanned') in (True, 'likely'))}")
    print(f"  Errors: {sum(1 for r in results if r.get('error'))}")
    print(f"\nOutput: {BASELINE_PATH}")


if __name__ == '__main__':
    main()
