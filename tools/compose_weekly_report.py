#!/usr/bin/env python3
"""
Compose a weekly HTML progress report using Claude.

Takes the week's mistake data (from sheets_query_mistakes.py), sends it to Claude
for analysis, and renders a clean HTML email using a Jinja2 template.

Reads from .env:
    ANTHROPIC_API_KEY

Usage:
    python tools/sheets_query_mistakes.py --since 2026-05-13 | \
        python tools/compose_weekly_report.py --since 2026-05-13 --until 2026-05-19

Output: HTML file at .tmp/report_<since>.html — prints the file path to stdout.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from jinja2 import Template

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"

REPORT_TOOL = {
    "name": "submit_report_data",
    "description": "Submit the structured data for the weekly English learning report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "top_patterns": {
                "type": "array",
                "description": "The 3 most important recurring patterns from this week.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "count": {"type": "integer"},
                        "teaching_note": {"type": "string", "description": "2-3 sentences explaining this pattern simply and memorably."},
                        "example": {
                            "type": "object",
                            "properties": {
                                "original": {"type": "string"},
                                "correction": {"type": "string"},
                            },
                            "required": ["original", "correction"],
                        },
                    },
                    "required": ["tag", "count", "teaching_note", "example"],
                },
            },
            "strengths_note": {
                "type": "string",
                "description": "1-2 sentences about something genuinely positive from this week's writing.",
            },
            "focus_next_week": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "daily_exercise": {"type": "string", "description": "One specific, concrete daily exercise (2-3 sentences) Maahi can do to fix this pattern."},
                },
                "required": ["tag", "daily_exercise"],
            },
            "encouragement": {
                "type": "string",
                "description": "1 short, genuine sentence of encouragement. Not generic — reference something specific from the writing.",
            },
        },
        "required": ["top_patterns", "strengths_note", "focus_next_week", "encouragement"],
    },
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 600px; margin: 0 auto; padding: 24px; color: #1a1a1a; }
  h1 { font-size: 22px; font-weight: 700; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; }
  h2 { font-size: 16px; font-weight: 600; color: #374151; margin-top: 28px; }
  .stats { display: flex; gap: 24px; background: #f9fafb; border-radius: 8px;
           padding: 16px; margin: 16px 0; }
  .stat { text-align: center; }
  .stat-value { font-size: 28px; font-weight: 700; color: #2563eb; }
  .stat-label { font-size: 12px; color: #6b7280; margin-top: 2px; }
  .pattern { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
             padding: 16px; margin: 12px 0; }
  .pattern-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .pattern-count { background: #dbeafe; color: #1d4ed8; font-size: 12px;
                   font-weight: 600; padding: 2px 8px; border-radius: 12px; }
  .pattern-tag { font-family: monospace; font-size: 13px; color: #6b7280; }
  .example { background: #fef2f2; border-left: 3px solid #ef4444;
             padding: 8px 12px; margin: 8px 0; border-radius: 0 4px 4px 0; }
  .correction { background: #f0fdf4; border-left: 3px solid #22c55e;
                padding: 8px 12px; margin: 8px 0; border-radius: 0 4px 4px 0; }
  .note { color: #374151; font-size: 14px; line-height: 1.6; }
  .focus-box { background: #fffbeb; border: 1px solid #fbbf24; border-radius: 8px;
               padding: 16px; margin: 12px 0; }
  .encouragement { background: #f0fdf4; border-radius: 8px; padding: 16px;
                   font-style: italic; color: #166534; margin: 16px 0; }
  .footer { font-size: 12px; color: #9ca3af; margin-top: 32px;
            padding-top: 16px; border-top: 1px solid #e5e7eb; }
</style>
</head>
<body>

<h1>English Learning — Week of {{ since }}</h1>

<div class="stats">
  <div class="stat">
    <div class="stat-value">{{ total_entries }}</div>
    <div class="stat-label">entries analyzed</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ total_mistakes }}</div>
    <div class="stat-label">mistakes found</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ avg_per_entry }}</div>
    <div class="stat-label">avg / entry</div>
  </div>
</div>

<h2>Top patterns this week</h2>

{% for p in top_patterns %}
<div class="pattern">
  <div class="pattern-header">
    <span class="pattern-count">{{ p.count }}x</span>
    <span class="pattern-tag">{{ p.tag }}</span>
  </div>
  <div class="example">{{ p.example.original }}</div>
  <div class="correction">{{ p.example.correction }}</div>
  <p class="note">{{ p.teaching_note }}</p>
</div>
{% endfor %}

<h2>What you did well</h2>
<p>{{ strengths_note }}</p>

<h2>Focus for next week</h2>
<div class="focus-box">
  <strong>{{ focus_next_week.tag }}</strong>
  <p>{{ focus_next_week.daily_exercise }}</p>
</div>

<div class="encouragement">{{ encouragement }}</div>

<div class="footer">
  Generated by your English Learning Agent &mdash; {{ generated_at }}<br>
  View full mistake log: <a href="{{ sheet_url }}">Google Sheet</a>
</div>

</body>
</html>"""


def get_report_data(mistakes, since, until):
    counts = Counter(m["tag"] for m in mistakes)
    top_tags = [t for t, _ in counts.most_common(3)]

    examples = {}
    for m in mistakes:
        if m["tag"] not in examples:
            examples[m["tag"]] = m

    summary = {
        "total_mistakes": len(mistakes),
        "total_entries": len({m["source_ref"] for m in mistakes}),
        "date_range": f"{since} to {until}",
        "top_patterns_raw": [
            {"tag": t, "count": counts[t], "example": {
                "original": examples[t]["original"],
                "correction": examples[t]["correction"],
            }}
            for t in top_tags
        ],
        "severity_counts": dict(Counter(m["severity"] for m in mistakes)),
    }

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        tools=[REPORT_TOOL],
        tool_choice={"type": "tool", "name": "submit_report_data"},
        system=(
            "You are an English teacher writing a weekly progress email for Maahi, "
            "an indie iOS developer improving from B1 to B2 English. "
            "Be direct, specific, and encouraging. Never generic."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Here is Maahi's writing mistake data for the week of {since}:\n\n"
                f"{json.dumps(summary, indent=2)}\n\n"
                "Submit the report data using the submit_report_data tool."
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_report_data":
            return block.input

    raise RuntimeError("Claude did not call submit_report_data")


def main():
    parser = argparse.ArgumentParser(description="Compose weekly HTML report.")
    parser.add_argument("--since", required=True, help="Week start YYYY-MM-DD")
    parser.add_argument("--until", help="Week end YYYY-MM-DD (default today)")
    parser.add_argument("--mistakes-json", help="JSON file from sheets_query_mistakes (default stdin)")
    args = parser.parse_args()

    until = args.until or datetime.now(timezone.utc).date().isoformat()

    load_dotenv(REPO_ROOT / ".env", override=True)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    if args.mistakes_json:
        mistakes = json.loads(Path(args.mistakes_json).read_text())
    else:
        mistakes = json.loads(sys.stdin.read())

    if not mistakes:
        print("No mistakes in date range — nothing to report", file=sys.stderr)
        sys.exit(0)

    print(f"Composing report for {len(mistakes)} mistakes across {len({m['source_ref'] for m in mistakes})} entries...", file=sys.stderr)
    data = get_report_data(mistakes, args.since, until)

    total_entries = len({m["source_ref"] for m in mistakes})
    avg = round(len(mistakes) / total_entries, 1) if total_entries else 0
    sheet_id = os.getenv("GSHEET_MISTAKE_LOG_ID", "")

    html = Template(HTML_TEMPLATE).render(
        since=args.since,
        until=until,
        total_entries=total_entries,
        total_mistakes=len(mistakes),
        avg_per_entry=avg,
        top_patterns=data.get("top_patterns", []),
        strengths_note=data.get("strengths_note") or data.get("strengths") or "",
        focus_next_week=data.get("focus_next_week", {"tag": "", "daily_exercise": ""}),
        encouragement=data.get("encouragement", ""),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}",
    )

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"report_{args.since}.html"
    out.write_text(html, encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
