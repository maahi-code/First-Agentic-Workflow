#!/usr/bin/env python3
"""
Query the Mistake Log Sheet by date range and optional tag filter.

Reads from .env:
    GSHEET_MISTAKE_LOG_ID

Usage:
    python tools/sheets_query_mistakes.py --since 2026-05-13
    python tools/sheets_query_mistakes.py --since 2026-05-13 --until 2026-05-19
    python tools/sheets_query_mistakes.py --since 2026-05-13 --tag subject-verb-agreement

Output (stdout): JSON array of mistake objects (same columns as the Sheet).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent

COLUMNS = [
    "id", "date", "source", "source_ref", "original", "correction",
    "mistake_type", "tag", "explanation", "severity", "cefr_focus", "created_at",
]


def row_to_dict(row):
    d = {}
    for i, col in enumerate(COLUMNS):
        d[col] = row[i] if i < len(row) else ""
    return d


def main():
    parser = argparse.ArgumentParser(description="Query mistakes from the Sheet.")
    parser.add_argument("--since", required=True, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--until", help="End date YYYY-MM-DD (inclusive, default today)")
    parser.add_argument("--tag", help="Filter to a specific tag (partial match)")
    args = parser.parse_args()

    until = args.until or datetime.now(timezone.utc).date().isoformat()

    load_dotenv(REPO_ROOT / ".env", override=True)
    sheet_id = os.getenv("GSHEET_MISTAKE_LOG_ID")
    if not sheet_id:
        print("GSHEET_MISTAKE_LOG_ID missing from .env", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="mistakes!A2:L100000",
    ).execute()
    raw_rows = result.get("values", [])

    mistakes = []
    for row in raw_rows:
        d = row_to_dict(row)
        date = d.get("date", "")
        if not date:
            continue
        if date < args.since or date > until:
            continue
        if args.tag and args.tag.lower() not in d.get("tag", "").lower():
            continue
        mistakes.append(d)

    print(json.dumps(mistakes, ensure_ascii=False))


if __name__ == "__main__":
    main()
