#!/usr/bin/env python3
"""
Send the weekly HTML report as an email via the Gmail API.

Uses the same Google OAuth token as Drive and Sheets — no extra credentials.
Sends from ms4341547@gmail.com to REPORT_TO_EMAIL (same address by default).

Reads from .env:
    REPORT_TO_EMAIL

Usage:
    python tools/send_gmail_report.py --html-file .tmp/report_2026-05-13.html \
        --subject "English Learning — Week of May 13"

Output (stdout): JSON {message_id, to, subject}
"""
import argparse
import base64
import json
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_message(to, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def main():
    parser = argparse.ArgumentParser(description="Send weekly report via Gmail.")
    parser.add_argument("--html-file", required=True, help="Path to the HTML report file")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--to", help="Recipient (default: REPORT_TO_EMAIL from .env)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    to = args.to or os.getenv("REPORT_TO_EMAIL")
    if not to:
        print("REPORT_TO_EMAIL missing from .env (or pass --to)", file=sys.stderr)
        sys.exit(1)

    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f"HTML file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    html_body = html_path.read_text(encoding="utf-8")

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)
    message = build_message(to, args.subject, html_body)
    sent = service.users().messages().send(userId="me", body=message).execute()

    print(json.dumps({
        "message_id": sent["id"],
        "to": to,
        "subject": args.subject,
    }))


if __name__ == "__main__":
    main()
