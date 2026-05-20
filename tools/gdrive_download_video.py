#!/usr/bin/env python3
"""
Download one speaking video from Google Drive to .tmp/.

Usage:
    python tools/gdrive_download_video.py --file-id <id> --name speaking_day75.mov
    python tools/gdrive_download_video.py --file-id <id>  # uses Drive filename

Output (stdout): JSON {file_id, local_path, size_bytes}
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp" / "videos"


def main():
    parser = argparse.ArgumentParser(description="Download one video from Drive.")
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--name", help="Local filename (default: Drive filename)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)

    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)

    meta = service.files().get(fileId=args.file_id, fields="name,size").execute()
    local_name = args.name or meta["name"]

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = TMP_DIR / local_name

    request = service.files().get_media(fileId=args.file_id)
    with open(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    size = local_path.stat().st_size
    print(json.dumps({
        "file_id": args.file_id,
        "local_path": str(local_path),
        "size_bytes": size,
    }))


if __name__ == "__main__":
    main()
