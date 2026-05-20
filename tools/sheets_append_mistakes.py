#!/usr/bin/env python3
"""
Append mistake rows to the "mistakes" tab of the Mistake Log Google Sheet.

Reads from .env:
    GSHEET_MISTAKE_LOG_ID

Usage:
    python tools/sheets_append_mistakes.py --analysis-json .tmp/analysis_<id>.json
    cat analysis.json | python tools/sheets_append_mistakes.py --stdin

Input: the JSON output of analyze_text.py (the full envelope: entry metadata +
.analysis with mistakes/patterns/strengths/naturalness_score). Each item in
.analysis.mistakes becomes one row.

Output (stdout): JSON {appended: N, sheet_url, row_ids: [...]}.

Column order (must match the bootstrap headers):
    id | date | source | source_ref | original | correction |
    mistake_type | tag | explanation | severity | cefr_focus | created_at | naturalness_score
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_rows(envelope):
    """Transform an analyze_text.py envelope into Sheet rows."""
    analysis = envelope.get("analysis", {}) or {}
    mistakes = analysis.get("mistakes", []) or []
    kind = envelope.get("kind", "writing")
    source_ref = envelope.get("page_id") or envelope.get("file_id") or ""

    created_time = envelope.get("created_time") or ""
    date = created_time[:10] if created_time else datetime.now(timezone.utc).date().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    naturalness = (envelope.get("analysis") or {}).get("naturalness_score", "")

    rows = []
    for m in mistakes:
        rows.append([
            str(uuid.uuid4()),
            date,
            kind,
            source_ref,
            m.get("original", ""),
            m.get("correction", ""),
            m.get("mistake_type", ""),
            m.get("tag", ""),
            m.get("explanation", ""),
            m.get("severity", ""),
            m.get("cefr_focus", ""),
            now_iso,
            naturalness,
        ])
    return rows


def main():
    parser = argparse.ArgumentParser(description="Append mistakes to the Mistake Log Sheet.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--analysis-json", help="Path to an analyze_text.py output file")
    src.add_argument("--stdin", action="store_true", help="Read the envelope JSON from stdin")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    sheet_id = os.getenv("GSHEET_MISTAKE_LOG_ID")
    if not sheet_id:
        print("GSHEET_MISTAKE_LOG_ID missing from .env", file=sys.stderr)
        sys.exit(1)

    if args.analysis_json:
        envelope = json.loads(Path(args.analysis_json).read_text(encoding="utf-8"))
    else:
        envelope = json.loads(sys.stdin.read())

    rows = build_rows(envelope)

    if not rows:
        print(json.dumps({"appended": 0, "note": "no mistakes in analysis"}))
        return

    try:
        creds = get_credentials()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    service = build("sheets", "v4", credentials=creds)
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="mistakes!A:M",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    print(json.dumps({
        "appended": len(rows),
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}",
        "row_ids": [r[0] for r in rows],
    }))


if __name__ == "__main__":
    main()
