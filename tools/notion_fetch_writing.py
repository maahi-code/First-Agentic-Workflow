#!/usr/bin/env python3
"""
Fetch entries from Notion's "Daily Writing Practice" database since a given date.

Reads from .env:
    NOTION_TOKEN              — integration secret (https://notion.so/my-integrations)
    NOTION_WRITING_DB_ID      — database ID (32-char from the DB URL, hyphens optional)

Usage:
    python tools/notion_fetch_writing.py --since 2026-05-13
    python tools/notion_fetch_writing.py --since 2026-05-13 --db-id <override>
    python tools/notion_fetch_writing.py --since 2026-05-13 --mode property --property Entry

Prints a JSON array to stdout (one element per page):
    [{
        "page_id": "...",
        "title": "Day 74 — 2026-05-19",
        "created_time": "2026-05-19T08:30:00.000Z",
        "last_edited_time": "...",
        "text": "the actual writing",
        "url": "https://www.notion.so/..."
    }, ...]

Also writes the same JSON to .tmp/writing_<since>.json for inspection.

Two modes for where the writing text lives:
    --mode blocks (default)  — page body (heading/paragraph/list/etc. blocks)
    --mode property          — a rich-text DB property named via --property

If you set up Daily Writing Practice as "one page per day, write in the body,"
the default works. If you keep the writing in a dedicated column (less common),
use --mode property.

Reading is filtered by Notion's `created_time` timestamp, which is stable
(doesn't change on edits) — important so re-runs don't re-ingest edits forever.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"

TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "quote",
    "callout",
    "to_do",
    "toggle",
}


def rich_text_to_plain(rich_text):
    return "".join(rt.get("plain_text", "") for rt in rich_text or [])


def block_text(block):
    btype = block.get("type")
    if btype not in TEXT_BLOCK_TYPES:
        return ""
    inner = block.get(btype, {})
    return rich_text_to_plain(inner.get("rich_text", []))


def fetch_page_body(client, page_id):
    chunks = []
    cursor = None
    while True:
        resp = client.blocks.children.list(block_id=page_id, start_cursor=cursor)
        for block in resp.get("results", []):
            text = block_text(block)
            if text:
                chunks.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n".join(chunks).strip()


def fetch_property_text(page, property_name):
    prop = page.get("properties", {}).get(property_name)
    if not prop:
        return ""
    ptype = prop.get("type")
    if ptype == "rich_text":
        return rich_text_to_plain(prop.get("rich_text", []))
    if ptype == "title":
        return rich_text_to_plain(prop.get("title", []))
    return ""


def page_title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return rich_text_to_plain(prop.get("title", []))
    return ""


def query_database(client, db_id, since_iso):
    # client.databases.query() was removed in notion-client >=2.3; call the REST endpoint directly
    cursor = None
    while True:
        body = {
            "filter": {
                "timestamp": "created_time",
                "created_time": {"on_or_after": since_iso},
            },
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        }
        if cursor:
            body["start_cursor"] = cursor
        resp = client.request(
            path=f"databases/{db_id}/query",
            method="POST",
            body=body,
        )
        for page in resp.get("results", []):
            yield page
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")


def main():
    parser = argparse.ArgumentParser(description="Fetch Notion writing entries since a date.")
    parser.add_argument("--since", required=True, help="ISO date YYYY-MM-DD")
    parser.add_argument("--db-id", help="Override NOTION_WRITING_DB_ID from .env")
    parser.add_argument(
        "--mode",
        choices=["blocks", "property"],
        default="blocks",
        help="Where to read writing from. blocks = page body, property = a rich-text DB property",
    )
    parser.add_argument(
        "--property",
        default="Entry",
        help="Property name when --mode=property (default: Entry)",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("NOTION_TOKEN missing from .env", file=sys.stderr)
        sys.exit(1)

    db_id = args.db_id or os.getenv("NOTION_WRITING_DB_ID")
    if not db_id:
        print("NOTION_WRITING_DB_ID missing from .env (or pass --db-id)", file=sys.stderr)
        sys.exit(1)

    try:
        datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError:
        print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
        sys.exit(1)
    # Use IST midnight (UTC+05:30) so entries written late at night IST
    # (which land on the previous UTC date) are still captured.
    since_iso = f"{args.since}T00:00:00+05:30"

    # Pin to 2022-06-28: the databases.query endpoint was moved in Notion API 2025-09-03
    client = Client(auth=token, notion_version="2022-06-28")

    entries = []
    for page in query_database(client, db_id, since_iso):
        page_id = page["id"]
        if args.mode == "blocks":
            text = fetch_page_body(client, page_id)
        else:
            text = fetch_property_text(page, args.property)
        entries.append({
            "page_id": page_id,
            "title": page_title(page),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "text": text,
            "url": page.get("url"),
        })

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dump_path = TMP_DIR / f"writing_{args.since}.json"
    dump_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False))

    print(json.dumps(entries, ensure_ascii=False))


if __name__ == "__main__":
    main()
