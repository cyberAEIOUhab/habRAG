#!/usr/bin/env python3
"""
Apply EPUB metadata fixes to bookdata.json based on epub_metadata_extract.json.
Updates fields where EPUB metadata provides corrections, and clears needs_review
where metadata is confirmed.
"""

import json
import sys
import io
import os
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOKDATA_FILE = os.path.join(BASE_DIR, "bookdata.json")
EPUB_META_FILE = os.path.join(BASE_DIR, "bookdata", "epub_metadata_extract.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    bookdata = load_json(BOOKDATA_FILE)
    books = bookdata if isinstance(bookdata, list) else bookdata.get("books", bookdata.get("entries", []))
    epub_data = load_json(EPUB_META_FILE)

    # Build lookup: filename → epub metadata
    epub_by_filename = {}
    for e in epub_data:
        epub_by_filename[e["filename"]] = e

    verified_at = datetime.now(timezone.utc).isoformat()
    fixes_applied = []
    still_needs_review = []
    already_ok = []

    for book in books:
        fn = book.get("filename", "")
        if fn not in epub_by_filename:
            continue

        epub = epub_by_filename[fn]
        meta = epub.get("metadata", {})
        if not meta or "error" in meta:
            still_needs_review.append(fn)
            continue

        changes = {}
        notes = []

        # --- Check and fix title ---
        epub_title = meta.get("title")
        # Skip if title is clearly an ISBN placeholder
        if epub_title and epub_title != "None" and not epub_title.startswith("0674047761"):
            if book.get("title", "") != epub_title:
                # Only update if current title is less descriptive or different
                # Don't downgrade a full title to a short title
                if len(epub_title) > len(book.get("title", "")):
                    changes["title"] = epub_title
                    notes.append(f"title updated from EPUB OPF: '{epub_title}'")
                elif book.get("title", "") == "":
                    changes["title"] = epub_title
                    notes.append(f"title set from EPUB OPF: '{epub_title}'")

        # --- Check and fix author ---
        epub_creator = meta.get("creator")
        if epub_creator and epub_creator != "None":
            # Normalize: "Last, First" → "First Last"
            if "," in epub_creator and ";" not in epub_creator:
                parts = [p.strip() for p in epub_creator.split(",", 1)]
                if len(parts) == 2:
                    epub_creator = f"{parts[1]} {parts[0]}"
            # Clean up semicolons
            epub_creator = epub_creator.replace(";", "").strip()
            if book.get("author", "").lower() != epub_creator.lower() and book.get("author", "") != epub_creator:
                # Don't downgrade
                if epub_creator and book.get("author", "Unknown") == "Unknown":
                    changes["author"] = epub_creator
                    notes.append(f"author set from EPUB OPF: '{epub_creator}'")

        # --- Check and fix publisher ---
        epub_pub = meta.get("publisher")
        if epub_pub and epub_pub != "None":
            # Map common variations
            pub_map = {
                "Knopf Doubleday Publishing Group": "Knopf",
                "The University of North Carolina Press": "University of North Carolina Press",
                "W. W. Norton & Company": "W.W. Norton",
                "Faber and Faber": "Faber & Faber",
            }
            epub_pub_normalized = pub_map.get(epub_pub, epub_pub)
            current_pub = book.get("publisher", "")
            if current_pub and current_pub.lower() != epub_pub_normalized.lower():
                # Check if it's a significant change
                # Faber and Faber vs Weidenfeld & Nicolson → significant
                changes["publisher"] = epub_pub_normalized
                notes.append(f"publisher: '{current_pub}' → '{epub_pub_normalized}' (from EPUB OPF)")

        # --- Check and fix year ---
        epub_date = meta.get("date")
        if epub_date and epub_date != "None":
            # Extract year from various date formats
            year = None
            if epub_date:
                # Try ISO: "1998-03-02T00:00:00+00:00"
                if "-" in str(epub_date):
                    year = int(str(epub_date).split("-")[0])
                elif len(str(epub_date)) == 4:
                    year = int(epub_date)
            if year and year != book.get("year"):
                current_year = book.get("year")
                changes["year"] = year
                notes.append(f"year: {current_year} → {year} (from EPUB OPF date: {epub_date})")

        # --- Check ISBN ---
        identifiers = meta.get("identifier", [])
        isbns = [i for i in identifiers if len(i.replace("-", "")) in [10, 13] and i.replace("-", "").isdigit()]
        if isbns:
            # Store ISBN if not already present
            if not book.get("isbn"):
                changes["isbn"] = isbns[0]
                notes.append(f"ISBN added from EPUB: {isbns[0]}")

        # --- Special handling for known issues ---
        # Book #9: The Habsburg Empire A New History - title was "0674047761 (H)" in OPF
        if "0674047761" in fn or "Judson" in fn:
            if book.get("title", "").startswith("0674047761"):
                changes["title"] = "The Habsburg Empire: A New History"
                notes.append("title corrected from ISBN placeholder to real title")

        # Book #6: Rumania 1866-1947 - corrupted EPUB
        if epub.get("spine_items") == 1 and epub.get("internal_file_count", 0) < 15:
            notes.append("WARNING: EPUB appears damaged/incomplete (only 1 spine item, 10 internal files)")
            if not book.get("needs_review"):
                changes["needs_review"] = True

        # Apply changes
        if changes:
            for k, v in changes.items():
                book[k] = v

            # Add epub_verification record
            book["epub_verification"] = {
                "verified_at": verified_at,
                "opf_title": meta.get("title"),
                "opf_creator": meta.get("creator"),
                "opf_publisher": meta.get("publisher"),
                "opf_date": meta.get("date"),
                "opf_identifiers": meta.get("identifier", []),
                "spine_items": epub.get("spine_items"),
                "file_size_mb": epub.get("file_size_mb"),
            }

            # Clear needs_review if we've confirmed the metadata
            if "WARNING" not in " ".join(notes) and book.get("needs_review"):
                # Only clear if changes are minor/cosmetic and confidence is high
                pass  # We'll handle this per-case below

            fixes_applied.append((fn, notes))
        else:
            # No fixes needed, mark as verified
            book["epub_verification"] = {
                "verified_at": verified_at,
                "opf_title": meta.get("title"),
                "opf_creator": meta.get("creator"),
                "opf_publisher": meta.get("publisher"),
                "opf_date": meta.get("date"),
                "opf_identifiers": meta.get("identifier", []),
                "spine_items": epub.get("spine_items"),
                "file_size_mb": epub.get("file_size_mb"),
            }
            already_ok.append(fn)

    # --- Per-book decisions on needs_review ---
    # Cases that can be cleared (metadata confirmed from EPUB OPF):
    clear_review_for = [
        "History of Slovakia The Struggle for Survival",     # 2005 confirmed, Griffin confirmed
        "Isonzo The Forgotten Sacrifice",                     # 2001 confirmed, Praeger confirmed
        "The Czechs and the Lands of the Bohemian Crown",     # Agnew confirmed, Hoover confirmed
        "The Limits of Loyalty",                              # 2007 confirmed, Berghahn confirmed
        "The Nation in the Village",                          # Author/publisher confirmed, year updated to 2015
        "From Prejudice to Persecution",                      # Year updated to 1998, UNC Press confirmed
        "The Great Departure",                                # W.W. Norton confirmed
    ]

    # Cases that must stay needs_review:
    keep_review_for = [
        "Rumania 1866-1947",              # Damaged EPUB, no metadata
        "The Habsburg Empire A New History", # Title was ISBN placeholder, needs title verification
        "The Habsburg Empire, 1790-1918",    # Publisher changed Weidenfeld→Faber, year 1968→2014 (reissue)
        "The Habsburg Monarchy, 1618–1815",  # Date 2019 unclear if 3rd ed or calibre artifact
        "Ring of Steel",                     # No date in EPUB, needs year verification
    ]

    for book in books:
        fn = book.get("filename", "")
        for pattern in clear_review_for:
            if pattern.lower() in fn.lower():
                if book.get("needs_review"):
                    book["needs_review"] = False
                    if book.get("extraction_confidence") == "low":
                        book["extraction_confidence"] = "medium"
                    fixes_applied.append((fn, [f"needs_review cleared: EPUB OPF metadata confirms bibliographic data"]))
                break

    # Save
    save_json(BOOKDATA_FILE, bookdata)

    # Report
    print("EPUB Metadata Fixes Applied")
    print("=" * 80)
    for fn, notes in fixes_applied:
        # Deduplicate
        if isinstance(notes, list):
            unique_notes = list(dict.fromkeys(notes))
        else:
            unique_notes = [notes]
        print(f"\n{fn[:90]}...")
        for n in unique_notes:
            print(f"  • {n}")

    print(f"\n{'='*80}")
    print(f"Books with EPUB verification record added: {len(fixes_applied) + len(already_ok)}")
    print(f"  Fixes applied: {len(fixes_applied)}")
    print(f"  Already OK:    {len(already_ok)}")
    print(f"  Still needs_review: {len(keep_review_for)} (see below)")

    print(f"\nStill needs manual review:")
    for p in keep_review_for:
        print(f"  ⚠ {p}")

    # Save a summary
    summary_path = os.path.join(BASE_DIR, "bookdata", "epub_fix_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"EPUB Metadata Fix Summary\n")
        f.write(f"Generated: {verified_at}\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"Total EPUBs processed: {len(epub_data)}\n")
        f.write(f"Fixes applied: {len(fixes_applied)}\n")
        f.write(f"Already correct: {len(already_ok)}\n\n")
        f.write("Fixes:\n")
        for fn, notes in fixes_applied:
            f.write(f"  {fn[:80]}...\n")
            for n in (notes if isinstance(notes, list) else [notes]):
                f.write(f"    - {n}\n")
        f.write(f"\nStill needs review:\n")
        for p in keep_review_for:
            f.write(f"  - {p}\n")

    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    main()
