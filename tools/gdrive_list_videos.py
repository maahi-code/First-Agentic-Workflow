#!/usr/bin/env python3
"""
List unprocessed speaking videos in a Google Drive folder.

Reads from .env:
    GDRIVE_VIDEO_FOLDER_ID

Usage:
    python tools/gdrive_list_videos.py --since 2026-05-01
    python tools/gdrive_list_videos.py --since 2026-05-01 --folder-id <override>

Output (stdout): JSON array [{file_id, name, created_time, size_bytes, mime_type}]
Also writes to .tmp/videos_<since>.json.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"

VIDEO_MIME_PREFIXES = ("video/", "application/octet-stream")


def main():
    parser = argparse.ArgumentParser(description="List new speaking videos in Drive.")
    parser.add_argument("--since", required=True, help="ISO date YYYY-MM-DD")
    parser.add_argument("--folder-id", help="Override GDRIVE_VIDEO_FOLDER_ID from .env")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    folder_id = args.folder_id or os.getenv("GDRIVE_VIDEO_FOLDER_ID")
    if not folder_id:
        print("GDRIVE_VIDEO_FOLDER_ID missing from .env (or pass --folder-id)", file=sys.stderr)
        sys.exit(1)

    try:
        datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError:
        print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
        sys.exit(1)

    since_rfc = f"{args.since}T00:00:00"

    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)

    query = (
        f"'{folder_id}' in parents"
        f" and createdTime >= '{since_rfc}'"
        f" and trashed = false"
    )

    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, createdTime, size, mimeType)",
            orderBy="createdTime asc",
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            mime = f.get("mimeType", "")
            if any(mime.startswith(p) for p in VIDEO_MIME_PREFIXES) or mime == "":
                files.append({
                    "file_id": f["id"],
                    "name": f["name"],
                    "created_time": f.get("createdTime", ""),
                    "size_bytes": int(f.get("size", 0)),
                    "mime_type": mime,
                })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"videos_{args.since}.json"
    out.write_text(json.dumps(files, indent=2, ensure_ascii=False))
    print(json.dumps(files, ensure_ascii=False))


if __name__ == "__main__":
    main()
