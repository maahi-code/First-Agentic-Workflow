#!/usr/bin/env python3
"""
Daily ingest runner — called by launchd every morning at 08:00.

Writing pipeline:
  1. Check yesterday's exercises
  2. Fetch new Notion entries (IST midnight filter to catch late-night writing)
  3. Skip already-processed pages (prevents double-send on re-runs)
  4. Analyze mistakes via Claude
  5. Append to Writing Journal doc
  6. Send Writing Practice email (exercise feedback + mistakes + new exercises)

If no writing found → reminder email.
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

STATE_DIR = REPO_ROOT / ".tmp" / "state"
PENDING_EXERCISES_FILE = STATE_DIR / "pending_exercises.json"
PROCESSED_PAGES_FILE = STATE_DIR / "processed_pages.json"
MISTAKES_HISTORY_FILE = STATE_DIR / "mistakes_history.json"


def run(args, **kwargs):
    return subprocess.run([PYTHON] + args, capture_output=True, text=True, cwd=str(REPO_ROOT), **kwargs)


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def get_env(key):
    """Read a value from .env without importing dotenv at module level."""
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env", override=True)
    return os.getenv(key, "").strip()


# ── streak ────────────────────────────────────────────────────────────────────

def update_streak():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    last = run(["tools/state_get.py", "--key", "last_activity_date", "--default", ""]).stdout.strip()
    streak = int(run(["tools/state_get.py", "--key", "current_streak", "--default", "0"]).stdout.strip() or 0)

    if last == today:
        return

    new_streak = streak + 1 if last == yesterday else 1
    run(["tools/state_set.py", "--key", "current_streak", "--value", str(new_streak)])
    run(["tools/state_set.py", "--key", "last_activity_date", "--value", today])

    longest = int(run(["tools/state_get.py", "--key", "longest_streak", "--default", "0"]).stdout.strip() or 0)
    if new_streak > longest:
        run(["tools/state_set.py", "--key", "longest_streak", "--value", str(new_streak)])

    log(f"Streak: {new_streak} day(s) (longest: {max(new_streak, longest)})")


# ── processed page-id deduplication ──────────────────────────────────────────

def load_processed_page_ids():
    if not PROCESSED_PAGES_FILE.exists():
        return set()
    try:
        return set(json.loads(PROCESSED_PAGES_FILE.read_text()))
    except Exception:
        return set()


def save_processed_page_ids(new_ids):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_processed_page_ids()
    combined = list(existing | new_ids)
    PROCESSED_PAGES_FILE.write_text(json.dumps(combined[-500:], ensure_ascii=False))


def append_to_mistakes_history(mistakes):
    """Append today's mistakes to the rolling 90-day history used by the weekly report."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if MISTAKES_HISTORY_FILE.exists():
        try:
            existing = json.loads(MISTAKES_HISTORY_FILE.read_text())
        except Exception:
            existing = []
    combined = existing + mistakes
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    combined = [r for r in combined if r.get("date", "") >= cutoff]
    MISTAKES_HISTORY_FILE.write_text(json.dumps(combined, ensure_ascii=False))


# ── pending exercise state ────────────────────────────────────────────────────

def load_pending_exercises():
    if not PENDING_EXERCISES_FILE.exists():
        return None
    try:
        return json.loads(PENDING_EXERCISES_FILE.read_text())
    except Exception:
        return None


def save_pending_exercises(page_id, exercises_list):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_EXERCISES_FILE.write_text(json.dumps({
        "page_id": page_id,
        "date": TODAY,
        "exercises": exercises_list,
    }, ensure_ascii=False))


def clear_pending_exercises():
    PENDING_EXERCISES_FILE.unlink(missing_ok=True)


# ── exercise checking ─────────────────────────────────────────────────────────

def check_pending_exercises():
    """Check yesterday's exercises. Returns (feedback_json_path | None, was_pending)."""
    pending = load_pending_exercises()
    if not pending:
        return None, False

    page_id = pending.get("page_id", "")
    exercises = pending.get("exercises", [])
    ex_date = pending.get("date", "")

    if not page_id or not exercises:
        clear_pending_exercises()
        return None, False

    log(f"Checking exercise answers for {ex_date} (page {page_id[:8]}...)")
    r = run([
        "tools/check_exercises.py",
        "--page-id", page_id,
        "--exercises", json.dumps(exercises),
        "--date", ex_date,
    ])

    clear_pending_exercises()

    if r.returncode != 0:
        log(f"Exercise check failed: {r.stderr.strip()[:120]}")
        return None, True

    try:
        result = json.loads(r.stdout.strip())
    except Exception:
        log("Exercise check returned invalid JSON")
        return None, True

    if not result.get("found"):
        log("No exercise answers found in yesterday's Notion page")
        return None, True

    n_correct = sum(1 for item in result.get("items", []) if item.get("correct"))
    n_total = len(result.get("items", []))
    log(f"Exercise check done: {n_correct}/{n_total} correct")

    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    feedback_path = tmp / f"exercise_feedback_{ex_date}.json"
    feedback_path.write_text(json.dumps(result, ensure_ascii=False))
    return str(feedback_path), True


# ── writing pipeline ──────────────────────────────────────────────────────────

def run_writing_pipeline():
    log("=== Writing pipeline start ===")

    # 1. Check yesterday's exercises
    feedback_path, exercise_pending = check_pending_exercises()

    # 2. Fetch from Notion
    r = run(["tools/state_get.py", "--key", "last_writing_sync", "--default", "2026-01-01"])
    since = r.stdout.strip() or "2026-01-01"
    log(f"Writing since: {since}")

    r = run(["tools/notion_fetch_writing.py", "--since", since])
    if r.returncode != 0:
        log(f"ERROR fetching Notion: {r.stderr.strip()}")
        _send_reminder_email()
        return

    try:
        entries = json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"ERROR parsing Notion output: {r.stdout[:200]}")
        return

    if not entries:
        log("No new writing entries — sending reminder.")
        _send_reminder_email()
        return

    # 3. Filter out already-processed pages (prevents duplicate emails on re-runs)
    processed_ids = load_processed_page_ids()
    new_entries = [e for e in entries if e.get("page_id") not in processed_ids]
    skipped = len(entries) - len(new_entries)
    if skipped:
        log(f"Skipping {skipped} already-processed page(s)")
    if not new_entries:
        log("All fetched entries already processed — sending reminder.")
        _send_reminder_email()
        return

    log(f"Found {len(new_entries)} new entries")
    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    all_ok = True
    analyses = []

    # 4. Analyze each entry
    for i, entry in enumerate(new_entries):
        if not (entry.get("text") or "").strip():
            log(f"  Entry {i+1} ({entry.get('title','?')}): empty, skipping")
            continue

        entry_path = tmp / f"entry_daily_{i:02d}.json"
        entry_path.write_text(json.dumps(entry, ensure_ascii=False))

        r = run(["tools/analyze_text.py", "--entry-json", str(entry_path), "--kind", "writing"])
        if r.returncode != 0:
            log(f"  Entry {i+1}: analysis failed — {r.stderr.strip()[:100]}")
            all_ok = False
            continue

        result = json.loads(r.stdout)
        analyses.append(result)
        n = len((result.get("analysis") or {}).get("mistakes") or [])
        log(f"  Entry {i+1} ({entry.get('title','?')}): {n} mistakes")

    if not all_ok:
        log("Some entries failed — NOT advancing sync date")
        return

    # Flatten mistakes (include page_id so weekly report can count unique entries)
    mistakes = []
    for a in analyses:
        pid = a.get("page_id", "")
        for m in (a.get("analysis") or {}).get("mistakes") or []:
            mc = dict(m)
            mc["date"] = TODAY
            mc["page_id"] = pid
            mistakes.append(mc)

    # Compute average naturalness
    scores = [
        (a.get("analysis") or {}).get("naturalness_score")
        for a in analyses
        if (a.get("analysis") or {}).get("naturalness_score")
    ]
    avg_naturalness = round(sum(scores) / len(scores)) if scores else None

    # Advance sync date + streak + mark pages as processed
    run(["tools/state_set.py", "--key", "last_writing_sync", "--value", TODAY])
    log(f"Writing sync advanced to {TODAY}")
    new_ids = {e.get("page_id") for e in new_entries if e.get("page_id")}
    save_processed_page_ids(new_ids)
    if mistakes:
        append_to_mistakes_history(mistakes)
        log(f"Appended {len(mistakes)} mistakes to history")
    update_streak()

    # 5. Append to Writing Journal doc
    if mistakes:
        mistakes_path = tmp / f"today_mistakes_writing_{TODAY}.json"
        mistakes_path.write_text(json.dumps(mistakes, ensure_ascii=False))

        cmd = [
            "tools/gdoc_append_review.py",
            "--mistakes-json", str(mistakes_path),
            "--date", TODAY,
            "--kind", "writing",
        ]
        if avg_naturalness:
            cmd += ["--naturalness", str(avg_naturalness)]

        r = run(cmd)
        if r.returncode == 0:
            doc_result = json.loads(r.stdout.strip() or "{}")
            writing_doc_url = doc_result.get("doc_url", "")
            log(f"Writing doc updated → {writing_doc_url}")
        else:
            log(f"Writing doc failed: {r.stderr.strip()[:120]}")
            writing_doc_url = ""
    else:
        log("No mistakes — skipping writing doc")
        writing_doc_url = _get_doc_url()

    # 6. Send Writing Practice email
    _send_writing_email(mistakes, analyses, new_entries, feedback_path, exercise_pending, writing_doc_url)

    log("=== Writing pipeline done ===")


def _send_writing_email(mistakes, analyses, entries, feedback_path, exercise_pending, doc_url):
    if not mistakes:
        log("No writing mistakes — skipping writing email")
        return

    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    mistakes_path = tmp / f"today_mistakes_writing_{TODAY}.json"
    mistakes_path.write_text(json.dumps(mistakes, ensure_ascii=False))

    if not doc_url:
        doc_url = _get_doc_url()

    cmd = [
        "tools/compose_daily_exercise.py",
        "--mistakes-json", str(mistakes_path),
        "--date", TODAY,
    ]
    if feedback_path:
        cmd += ["--exercise-feedback-json", feedback_path]
    if exercise_pending and not feedback_path:
        cmd += ["--exercise-feedback-pending"]
    if doc_url:
        cmd += ["--doc-url", doc_url]

    r = run(cmd)
    if r.returncode != 0:
        log(f"Writing email compose failed: {r.stderr.strip()[:120]}")
        return

    html_path = r.stdout.strip()
    if not html_path or not Path(html_path).exists():
        log("Writing email compose returned no file")
        return

    r2 = run([
        "tools/send_gmail_report.py",
        "--html-file", html_path,
        "--subject", f"Writing Practice — {TODAY} ({len(mistakes)} mistakes)",
    ])
    if r2.returncode == 0:
        log(f"Writing email sent ({len(mistakes)} mistakes)")
    else:
        log(f"Writing email send failed: {r2.stderr.strip()[:120]}")

    # Save exercises for tomorrow's check (use most recent entry's page_id)
    sidecar = REPO_ROOT / ".tmp" / f"exercise_data_{TODAY}.json"
    exercises_list = []
    try:
        exercises_list = json.loads(sidecar.read_text()).get("exercises", [])
    except Exception:
        pass

    first_page_id = ""
    for entry in reversed(entries):
        if entry.get("page_id"):
            first_page_id = entry["page_id"]
            break

    if exercises_list and first_page_id:
        save_pending_exercises(first_page_id, exercises_list)
        log(f"Saved {len(exercises_list)} exercises for tomorrow's check")


def _send_reminder_email():
    streak = run(["tools/state_get.py", "--key", "current_streak", "--default", "0"]).stdout.strip() or "0"
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 480px; margin: 0 auto; padding: 20px; color: #1a1a1a; }}
  .box {{ background: #fef9c3; border: 1px solid #fbbf24; border-radius: 8px;
          padding: 20px 24px; }}
  h1 {{ font-size: 17px; margin: 0 0 8px; color: #713f12; }}
  p  {{ font-size: 14px; color: #374151; margin: 8px 0 0; line-height: 1.6; }}
  .streak {{ font-size: 13px; color: #92400e; margin-top: 12px; font-weight: 600; }}
</style>
</head>
<body>
<div class="box">
  <h1>No writing found today</h1>
  <p>Your English agent ran at 8 AM and found nothing new in Notion. Write something — even a few sentences counts!</p>
  <p class="streak">Current streak: {streak} day(s). Don't break it.</p>
</div>
</body>
</html>"""

    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    path = tmp / f"reminder_{TODAY}.html"
    path.write_text(html, encoding="utf-8")

    r = run(["tools/send_gmail_report.py", "--html-file", str(path),
             "--subject", f"Write something today — {TODAY}"])
    if r.returncode == 0:
        log("Reminder email sent")
    else:
        log(f"Reminder email failed: {r.stderr.strip()[:120]}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_doc_url():
    doc_id = get_env("GDOC_WRITING_ID") or get_env("GDOC_JOURNAL_ID")
    return f"https://docs.google.com/document/d/{doc_id}" if doc_id else ""


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log(f"Daily ingest starting — {TODAY}")
    run_writing_pipeline()
    log("Daily ingest complete")
