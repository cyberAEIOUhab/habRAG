"""
Write a batch of book entries to bookdata.json.
Reads entries from a JSON file and appends to bookdata.json.
Usage: python write_batch.py <batch_entries.json>
"""
import json, sys, os
from datetime import datetime

# The batch entries JSON file
batch_file = sys.argv[1] if len(sys.argv) > 1 else None

if batch_file and os.path.exists(batch_file):
    with open(batch_file, 'r', encoding='utf-8') as f:
        entries = json.load(f)
else:
    print(f"Usage: python write_batch.py <batch_entries.json>")
    sys.exit(1)

# Load baseline for bookmark data and other fields
baseline_path = 'baseline_extract.json'
baseline_by_fn = {}
if os.path.exists(baseline_path):
    with open(baseline_path, 'r', encoding='utf-8') as f:
        baseline = json.load(f)
    baseline_by_fn = {b['filename']: b for b in baseline}

# Populate fields from baseline
for entry in entries:
    fn = entry['filename']
    if fn in baseline_by_fn:
        b = baseline_by_fn[fn]
        bm = b.get('bookmark_titles')
        if bm and isinstance(bm, list):
            entry['bookmark_titles'] = [item['title'] for item in bm if isinstance(item, dict)]
        if 'is_scanned' not in entry or entry['is_scanned'] is None:
            entry['is_scanned'] = b.get('is_scanned')
        if 'has_bookmarks' not in entry or entry['has_bookmarks'] is None:
            entry['has_bookmarks'] = b.get('has_bookmarks')
        if 'page_count' not in entry or not entry['page_count']:
            entry['page_count'] = b.get('page_count', 0)

# Load existing bookdata
bookdata_path = 'bookdata.json'
existing = []
if os.path.exists(bookdata_path):
    with open(bookdata_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)

existing_fns = {b['filename'] for b in existing}
added = 0
for entry in entries:
    if entry['filename'] not in existing_fns:
        existing.append(entry)
        existing_fns.add(entry['filename'])
        added += 1

with open(bookdata_path, 'w', encoding='utf-8') as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

# Update log
log_path = 'log.txt'
for entry in entries:
    if entry['filename'] not in existing_fns:  # already counted
        continue
    # Check if already logged
    ts = datetime.now().isoformat()
    review = 'REVIEW' if entry.get('needs_review') else 'OK'
    conf = entry.get('extraction_confidence', '?')
    desc_src = entry.get('description_source', '?')
    with open(log_path, 'a', encoding='utf-8') as lf:
        lf.write(f"{entry['filename']} | DONE | {ts} | conf={conf} review={review} desc_src={desc_src}\n")

print(f'Added {added} books, total: {len(existing)}')
for e in entries[-added:] if added else entries:
    title = (e.get('title') or '?')[:70]
    author = (e.get('author') or '?')[:50]
    year = e.get('year', '?')
    conf = e.get('extraction_confidence', '?')
    print(f'  [{conf}] {title} | {author} | {year}')
