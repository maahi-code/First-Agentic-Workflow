#!/usr/bin/env python3
"""
Daily ingest runner — called by launchd every morning at 08:00.

Runs both writing and speaking ingests in sequence, following the
workflow SOPs in workflows/daily_ingest_writing.md and
workflows/daily_ingest_speaking.md.

After writing ingest: sends a targeted exercise email and updates streak.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
TODAY = datetime.now(timezone.utc).date().isoformat()


def run(args, **kwargs):
    return subprocess.run([PYTHON] + args, capture_output=True, text=True, cwd=str(REPO_ROOT), **kwargs)


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def update_streak():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    last = run(["tools/state_get.py", "--key", "last_activity_date", "--default", ""]).stdout.strip()
    streak = int(run(["tools/state_get.py", "--key", "current_streak", "--default", "0"]).stdout.strip() or 0)

    if last == today:
        return  # already updated this run

    new_streak = streak + 1 if last == yesterday else 1
    run(["tools/state_set.py", "--key", "current_streak", "--value", str(new_streak)])
    run(["tools/state_set.py", "--key", "last_activity_date", "--value", today])

    longest = int(run(["tools/state_get.py", "--key", "longest_streak", "--default", "0"]).stdout.strip() or 0)
    if new_streak > longest:
        run(["tools/state_set.py", "--key", "longest_streak", "--value", str(new_streak)])

    log(f"Streak: {new_streak} day(s) (longest: {max(new_streak, longest)})")


def send_daily_exercise(all_analyses):
    mistakes = []
    for a in all_analyses:
        for m in (a.get("analysis") or {}).get("mistakes") or []:
            m_copy = dict(m)
            m_copy["date"] = TODAY
            mistakes.append(m_copy)

    if not mistakes:
        log("No mistakes today — skipping exercise email")
        return

    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    mistakes_path = tmp / f"today_mistakes_{TODAY}.json"
    mistakes_path.write_text(json.dumps(mistakes, ensure_ascii=False))

    r = run(["tools/compose_daily_exercise.py", "--mistakes-json", str(mistakes_path), "--date", TODAY])
    if r.returncode != 0:
        log(f"Exercise compose failed: {r.stderr.strip()[:120]}")
        return

    html_path = r.stdout.strip()
    if not html_path or not Path(html_path).exists():
        log("Exercise compose returned no file path")
        return

    r2 = run([
        "tools/send_gmail_report.py",
        "--html-file", html_path,
        "--subject", f"Today's English Practice — {TODAY}",
    ])
    if r2.returncode == 0:
        log(f"Daily exercise email sent ({len(mistakes)} mistakes)")
    else:
        log(f"Exercise email send failed: {r2.stderr.strip()[:120]}")


def append_gdoc_review(all_analyses, kind):
    mistakes = []
    for a in all_analyses:
        for m in (a.get("analysis") or {}).get("mistakes") or []:
            m_copy = dict(m)
            m_copy["date"] = TODAY
            mistakes.append(m_copy)

    if not mistakes:
        log("No mistakes — skipping doc review")
        return

    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    mistakes_path = tmp / f"today_mistakes_{TODAY}.json"
    mistakes_path.write_text(json.dumps(mistakes, ensure_ascii=False))

    r = run([
        "tools/gdoc_append_review.py",
        "--mistakes-json", str(mistakes_path),
        "--date", TODAY,
        "--kind", kind,
    ])
    if r.returncode == 0:
        result = json.loads(r.stdout.strip() or "{}")
        log(f"Doc review appended → {result.get('doc_url', '?')}")
    else:
        log(f"Doc review failed: {r.stderr.strip()[:120]}")


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
    all_analyses = []

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

        analysis_result = json.loads(r.stdout)
        all_analyses.append(analysis_result)

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
        update_streak()
        send_daily_exercise(all_analyses)
        append_gdoc_review(all_analyses, "writing")

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
    all_ok = True
    all_analyses = []

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

        compress_out = json.loads(r.stdout)
        audio_path = compress_out["output_path"]
        ratio = compress_out.get("ratio", "?")
        log(f"    Compressed {ratio}x smaller → analyzing with Gemini")

        r = run(["tools/analyze_speaking_with_gemini.py", "--audio-path", audio_path, "--file-id", file_id])
        if r.returncode != 0:
            log(f"    Speaking analysis failed: {r.stderr.strip()[:100]}")
            all_ok = False
        else:
            analysis_result = json.loads(r.stdout)
            n = len((analysis_result.get("analysis") or {}).get("mistakes") or [])
            score = (analysis_result.get("analysis") or {}).get("naturalness_score", "?")
            log(f"    {n} issues found, naturalness score: {score}/10")
            all_analyses.append(analysis_result)

        Path(video_path).unlink(missing_ok=True)
        Path(audio_path).unlink(missing_ok=True)

    if all_ok:
        run(["tools/state_set.py", "--key", "last_video_sync", "--value", TODAY])
        log(f"Sync date advanced to {TODAY}")
        append_gdoc_review(all_analyses, "speaking")

    log(f"=== Speaking ingest done — {len(all_analyses)} video(s) analyzed ===")


if __name__ == "__main__":
    log(f"Daily ingest starting — {TODAY}")
    ingest_writing()
    ingest_speaking()
    log("Daily ingest complete")
