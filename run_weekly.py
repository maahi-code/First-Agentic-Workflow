#!/usr/bin/env python3
"""
Weekly report runner — called by launchd every Sunday at 19:00.

Reads the past 7 days from .tmp/state/mistakes_history.json (written by
run_daily.py after each successful analysis), composes a progress email,
sends it, and appends a weekly summary to the Writing Journal Google Doc.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
TODAY = datetime.now(timezone.utc).date()
SINCE = (TODAY - timedelta(days=7)).isoformat()
UNTIL = TODAY.isoformat()

MISTAKES_HISTORY_FILE = REPO_ROOT / ".tmp" / "state" / "mistakes_history.json"


def run(args, input=None):
    return subprocess.run(
        [PYTHON] + args,
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        input=input,
    )


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


if __name__ == "__main__":
    log(f"Weekly report starting — {SINCE} to {UNTIL}")

    # 1. Load mistake history and filter to past 7 days
    if not MISTAKES_HISTORY_FILE.exists():
        log("No mistake history file found — skipping (run_daily.py hasn't run yet?)")
        sys.exit(0)

    try:
        all_mistakes = json.loads(MISTAKES_HISTORY_FILE.read_text())
    except Exception as exc:
        log(f"ERROR reading mistakes history: {exc}")
        sys.exit(1)

    week_mistakes = [m for m in all_mistakes if SINCE <= m.get("date", "") <= UNTIL]

    if not week_mistakes:
        log("No mistakes recorded in the past 7 days — skipping report")
        sys.exit(0)

    n_entries = len({m.get("page_id", "") for m in week_mistakes if m.get("page_id")})
    log(f"Found {len(week_mistakes)} mistakes across {n_entries} entries")

    # Save filtered week to a temp file for compose step
    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    week_file = tmp / f"week_{SINCE}.json"
    week_file.write_text(json.dumps(week_mistakes, ensure_ascii=False))

    # Read streak from state
    streak = run(["tools/state_get.py", "--key", "current_streak", "--default", "0"]).stdout.strip() or "0"
    longest = run(["tools/state_get.py", "--key", "longest_streak", "--default", "0"]).stdout.strip() or "0"

    # 2. Compose report (one Claude Haiku call)
    r = run([
        "tools/compose_weekly_report.py",
        "--since", SINCE,
        "--until", UNTIL,
        "--mistakes-json", str(week_file),
        "--streak", streak,
        "--longest-streak", longest,
    ])
    if r.returncode != 0:
        log(f"ERROR composing report: {r.stderr.strip()}")
        sys.exit(1)

    html_path = r.stdout.strip()
    log(f"Report rendered: {html_path}")

    # 3. Send email
    subject = f"English Learning — Week of {SINCE}"
    r = run(["tools/send_gmail_report.py", "--html-file", html_path, "--subject", subject])
    if r.returncode != 0:
        log(f"ERROR sending email: {r.stderr.strip()}")
        log(f"Report saved at {html_path} — send manually if needed")
        sys.exit(1)

    result = json.loads(r.stdout)
    log(f"Email sent to {result['to']} (message_id: {result['message_id']})")

    # 4. Append weekly summary to Writing Journal Google Doc
    r = run([
        "tools/gdoc_append_review.py",
        "--mistakes-json", str(week_file),
        "--date", f"{SINCE}:{UNTIL}",
        "--kind", "weekly",
    ])
    if r.returncode == 0:
        doc_result = json.loads(r.stdout.strip() or "{}")
        log(f"Weekly doc summary appended → {doc_result.get('doc_url', '?')}")
    else:
        log(f"Weekly doc append failed: {r.stderr.strip()[:120]}")

    log("Weekly report complete")
