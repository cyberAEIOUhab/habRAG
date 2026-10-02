#!/usr/bin/env python3
"""
Remove epub_verification and scan_verification extra fields from bookdata.json,
integrating key findings into existing fields (extraction_notes, needs_review, etc.).
"""

import json, sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOKDATA = os.path.join(BASE_DIR, "bookdata.json")


def main():
    with open(BOOKDATA, 'r', encoding='utf-8') as f:
        data = json.load(f)
    books = data if isinstance(data, list) else data.get('books', data.get('entries', []))

    removed_epub = 0
    removed_scan = 0
    notes_updated = 0

    for book in books:
        fn = book.get('filename', '')[:60]
        modified = False

        # --- Integrate scan_verification ---
        sv = book.pop('scan_verification', None)
        if sv:
            removed_scan += 1
            existing_notes = book.get('extraction_notes', '') or ''
            scan_note = (
                f'[scan_verification 2026-07-29] '
                f'Sampled 5 pages (10%/25%/50%/75%/90%): '
                f'classification={sv["classification"]}, verdict={sv["verdict"]}. '
            )
            # Only add if not already in notes
            if 'scan_verification' not in existing_notes:
                if existing_notes:
                    book['extraction_notes'] = existing_notes + ' ' + scan_note
                else:
                    book['extraction_notes'] = scan_note
                notes_updated += 1

        # --- Integrate epub_verification ---
        ev = book.pop('epub_verification', None)
        if ev:
            removed_epub += 1
            existing_notes = book.get('extraction_notes', '') or ''

            # Build concise note
            parts = []
            if ev.get('opf_title'):
                parts.append(f'OPF title: "{ev["opf_title"]}"')
            if ev.get('opf_publisher'):
                parts.append(f'OPF publisher: {ev["opf_publisher"]}')
            if ev.get('opf_date'):
                parts.append(f'OPF date: {ev["opf_date"]}')
            if ev.get('opf_identifiers'):
                isbns = [i for i in ev['opf_identifiers'] if 'ISBN' in i.upper() or (len(i.replace('-','')) in [10,13] and i.replace('-','').isdigit())]
                if isbns:
                    parts.append(f'OPF ISBN: {isbns[0]}')

            epub_note = f'[epub_verification {ev.get("verified_at","")[:10]}] EPUB OPF parsed directly: {"; ".join(parts)}.'
            if 'epub_verification' not in existing_notes and 'EPUB OPF' not in existing_notes:
                if existing_notes:
                    book['extraction_notes'] = existing_notes + ' ' + epub_note
                else:
                    book['extraction_notes'] = epub_note
                notes_updated += 1

    # Save
    with open(BOOKDATA, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'Removed epub_verification from {removed_epub} books')
    print(f'Removed scan_verification from {removed_scan} books')
    print(f'Updated extraction_notes on {notes_updated} books')
    print('Done.')


if __name__ == '__main__':
    main()
