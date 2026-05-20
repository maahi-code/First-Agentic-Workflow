#!/usr/bin/env python3
"""
Daily ingest runner — called by launchd every morning at 08:00.

Runs both writing and speaking ingests in sequence, following the
workflow SOPs in workflows/daily_ingest_writing.md and
workflows/daily_ingest_speaking.md.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
TODAY = datetime.now(timezone.utc).date().isoformat()


def run(args, **kwargs):
    return subprocess.run([PYTHON] + args, capture_output=True, text=True, cwd=str(REPO_ROOT), **kwargs)


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def ingest_writing():
    log("=== Writing ingest start ===")

    r = run(["tools/state_get.py", "--key", "last_writing_sync", "--default", "2026-01-01"])
    since = r.stdout.strip() or "2026-01-01"
    log(f"Since: {since}")

    r = run(["tools/notion_fetch_writing.py", "--since", since])
    if r.returncode != 0:
        log(f"ERROR fetching Notion: {r.stderr.strip()}")
        return

    try:
        entries = json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"ERROR parsing Notion output: {r.stdout[:200]}")
        return

    if not entries:
        log("No new writing entries — skipping.")
        return

    log(f"Found {len(entries)} new entries")
    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    total_appended = 0
    all_ok = True

    for i, entry in enumerate(entries):
        if not (entry.get("text") or "").strip():
            log(f"  Entry {i+1} ({entry.get('title','?')}): empty text, skipping")
            continue

        entry_path = tmp / f"entry_daily_{i:02d}.json"
        entry_path.write_text(json.dumps(entry, ensure_ascii=False))

        r = run(["tools/analyze_text.py", "--entry-json", str(entry_path), "--kind", "writing"])
        if r.returncode != 0:
            log(f"  Entry {i+1} ({entry.get('title','?')}): analysis failed — {r.stderr.strip()[:100]}")
            all_ok = False
            continue

        r2 = run(["tools/sheets_append_mistakes.py", "--stdin"], input=r.stdout)
        if r2.returncode != 0:
            log(f"  Entry {i+1}: sheet append failed — {r2.stderr.strip()[:100]}")
            all_ok = False
            continue

        try:
            result = json.loads(r2.stdout)
            n = result.get("appended", 0)
            total_appended += n
            log(f"  Entry {i+1} ({entry.get('title','?')}): {n} mistakes appended")
        except Exception:
            log(f"  Entry {i+1}: appended (count unknown)")

    if all_ok:
        run(["tools/state_set.py", "--key", "last_writing_sync", "--value", TODAY])
        log(f"Sync date advanced to {TODAY}")

    log(f"=== Writing ingest done — {total_appended} mistakes appended ===")


def ingest_speaking():
    log("=== Speaking ingest start ===")

    r = run(["tools/state_get.py", "--key", "last_video_sync", "--default", "2026-01-01"])
    since = r.stdout.strip() or "2026-01-01"
    log(f"Since: {since}")

    r = run(["tools/gdrive_list_videos.py", "--since", since])
    if r.returncode != 0:
        log(f"ERROR listing Drive videos: {r.stderr.strip()}")
        return

    try:
        videos = json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"ERROR parsing video list: {r.stdout[:200]}")
        return

    if not videos:
        log("No new videos — skipping.")
        return

    log(f"Found {len(videos)} new videos")
    tmp = REPO_ROOT / ".tmp"
    all_ok = True
    total_appended = 0

    for v in videos:
        file_id = v["file_id"]
        name = v["name"]
        log(f"  Processing: {name}")

        r = run(["tools/gdrive_download_video.py", "--file-id", file_id, "--name", name])
        if r.returncode != 0:
            log(f"    Download failed: {r.stderr.strip()[:100]}")
            all_ok = False
            continue

        video_path = json.loads(r.stdout)["local_path"]

        r = run(["tools/compress_video_to_audio.py", "--video-path", video_path])
        if r.returncode != 0:
            log(f"    Compression failed: {r.stderr.strip()[:100]}")
            all_ok = False
            Path(video_path).unlink(missing_ok=True)
            continue

        audio_path = json.loads(r.stdout)["output_path"]
        ratio = json.loads(r.stdout).get("ratio", "?")
        log(f"    Compressed {ratio}x smaller")

        r = run(["tools/transcribe_with_gemini.py", "--audio-path", audio_path, "--file-id", file_id])
        if r.returncode != 0:
            log(f"    Transcription failed: {r.stderr.strip()[:100]}")
            all_ok = False
            Path(video_path).unlink(missing_ok=True)
            Path(audio_path).unlink(missing_ok=True)
            continue

        transcript_data = json.loads(r.stdout)
        if len((transcript_data.get("text") or "").split()) < 10:
            log(f"    Transcript too short — skipping analysis")
            Path(video_path).unlink(missing_ok=True)
            Path(audio_path).unlink(missing_ok=True)
            continue

        r = run(["tools/analyze_text.py", "--entry-json",
                 str(tmp / "transcripts" / f"{file_id}.json"), "--kind", "speaking"])
        if r.returncode != 0:
            log(f"    Analysis failed: {r.stderr.strip()[:100]}")
            all_ok = False
        else:
            r2 = run(["tools/sheets_append_mistakes.py", "--stdin"], input=r.stdout)
            n = json.loads(r2.stdout).get("appended", 0) if r2.returncode == 0 else 0
            total_appended += n
            log(f"    {n} mistakes appended")

        Path(video_path).unlink(missing_ok=True)
        Path(audio_path).unlink(missing_ok=True)

    if all_ok:
        run(["tools/state_set.py", "--key", "last_video_sync", "--value", TODAY])
        log(f"Sync date advanced to {TODAY}")

    log(f"=== Speaking ingest done — {total_appended} mistakes appended ===")


if __name__ == "__main__":
    log(f"Daily ingest starting — {TODAY}")
    ingest_writing()
    ingest_speaking()
    log("Daily ingest complete")
