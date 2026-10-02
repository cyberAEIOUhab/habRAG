#!/usr/bin/env python3
"""
Sync scan verification results into bookdata.json.

Reads scan_verification_results.json (produced by verify_scanned.py) and merges
a compact verification record into each matching book entry in bookdata.json.

Usage:
    python bookdata/scripts/sync_scan_verification.py
"""

import json
import sys
import io
import os
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOKDATA_DIR = os.path.join(BASE_DIR, "bookdata")
BOOKDATA_FILE = os.path.join(BASE_DIR, "bookdata.json")
RESULTS_FILE = os.path.join(BASE_DIR, "scan_verification_results.json")

# After sync, move results here
ARCHIVE_PATH = os.path.join(BOOKDATA_DIR, "scan_verification_results.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compact_sample(samples_dict):
    """Convert verbose samples dict to a compact list for storage."""
    compact = []
    for pct_key in sorted(samples_dict.keys(), key=float):
        s = samples_dict[pct_key]
        compact.append({
            "pct": float(pct_key),
            "page": s["page"],
            "chars": s["chars"],
        })
    return compact


def main():
    if not os.path.exists(RESULTS_FILE):
        print(f"ERROR: Results file not found: {RESULTS_FILE}")
        print("Run verify_scanned.py first to generate it.")
        sys.exit(1)

    # Load both files
    results = load_json(RESULTS_FILE)
    bookdata = load_json(BOOKDATA_FILE)
    books = bookdata if isinstance(bookdata, list) else bookdata.get("books", bookdata.get("entries", []))

    # Build lookup by filename
    results_by_filename = {}
    for r in results:
        results_by_filename[r["filename"]] = r

    verified_at = datetime.now(timezone.utc).isoformat()

    matched = 0
    unmatched = 0
    updated = 0

    for book in books:
        fn = book.get("filename", "")
        if fn in results_by_filename:
            matched += 1
            vr = results_by_filename[fn]

            verification_record = {
                "classification": vr["classification"],
                "verdict": vr["verdict"],
                "sample_pages": compact_sample(vr["samples"]),
                "verified_at": verified_at,
            }

            # Only update if the record has changed
            existing = book.get("scan_verification")
            if existing != verification_record:
                book["scan_verification"] = verification_record
                updated += 1

    # Handle results that didn't match any book
    all_filenames = {b.get("filename", "") for b in books}
    for fn in results_by_filename:
        if fn not in all_filenames:
            unmatched += 1
            print(f"  UNMATCHED: {fn[:100]}")

    # Save updated bookdata
    save_json(BOOKDATA_FILE, bookdata)
    print(f"Saved: {BOOKDATA_FILE}")
    print(f"  Books in bookdata.json: {len(books)}")
    print(f"  Verification results:    {len(results)}")
    print(f"  Matched & synced:        {matched}")
    print(f"  Actually updated:        {updated}")
    print(f"  Unmatched:               {unmatched}")

    # Move results file to bookdata/
    if os.path.abspath(RESULTS_FILE) != os.path.abspath(ARCHIVE_PATH):
        # Remove old archive if exists
        if os.path.exists(ARCHIVE_PATH):
            os.remove(ARCHIVE_PATH)
        os.rename(RESULTS_FILE, ARCHIVE_PATH)
        print(f"\nResults archived to: {ARCHIVE_PATH}")


if __name__ == "__main__":
    main()
