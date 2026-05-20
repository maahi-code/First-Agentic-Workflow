#!/usr/bin/env python3
"""
Weekly report runner — called by launchd every Sunday at 19:00.

Follows workflows/weekly_report.md.
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

    # 1. Query mistakes
    r = run(["tools/sheets_query_mistakes.py", "--since", SINCE, "--until", UNTIL])
    if r.returncode != 0:
        log(f"ERROR querying Sheet: {r.stderr.strip()}")
        sys.exit(1)

    mistakes = json.loads(r.stdout)
    if not mistakes:
        log("No mistakes this week — skipping report (no entries ingested?)")
        sys.exit(0)

    log(f"Found {len(mistakes)} mistakes across {len({m['source_ref'] for m in mistakes})} entries")

    # Save to file for compose step
    tmp = REPO_ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    week_file = tmp / f"week_{SINCE}.json"
    week_file.write_text(r.stdout)

    # 2. Compose report (one Claude Haiku call)
    r = run([
        "tools/compose_weekly_report.py",
        "--since", SINCE,
        "--until", UNTIL,
        "--mistakes-json", str(week_file),
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
    log("Weekly report complete")
