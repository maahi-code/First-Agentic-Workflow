#!/usr/bin/env python3
"""
Compose a short daily exercise email based on today's mistakes.

Picks the single most important pattern from today, generates 2-3 targeted
practice prompts using the actual mistakes as examples, and references the
exact English Grammar in Use unit to study.

Reads from .env:
    ANTHROPIC_API_KEY

Usage:
    python tools/compose_daily_exercise.py --mistakes-json .tmp/today_mistakes.json --date 2026-05-20

Input: JSON array of mistake dicts (same shape as mistakes tab rows).
Output: HTML file at .tmp/exercise_<date>.html — prints file path to stdout.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from jinja2 import Template

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"

EXERCISE_TOOL = {
    "name": "submit_exercise",
    "description": "Submit today's targeted English practice exercise.",
    "input_schema": {
        "type": "object",
        "properties": {
            "top_pattern": {
                "type": "string",
                "description": "The kebab-case tag slug of the most important pattern to fix today.",
            },
            "why_it_matters": {
                "type": "string",
                "description": "1-2 sentences: why this specific pattern blocks B2 fluency. Be direct.",
            },
            "exercises": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "description": "2-3 short practice prompts. Use Maahi's actual mistake examples from today — rewrite exercises or fill-in-the-blank. Each prompt is one sentence.",
                "items": {"type": "string"},
            },
            "book_reference": {
                "type": "object",
                "description": "Exact unit from 'English Grammar in Use' (Raymond Murphy, Cambridge) that covers this pattern.",
                "properties": {
                    "unit_number": {
                        "type": "integer",
                        "description": "The unit number in the book.",
                    },
                    "unit_title": {
                        "type": "string",
                        "description": "The exact unit title as it appears in the book.",
                    },
                    "why_relevant": {
                        "type": "string",
                        "description": "One sentence connecting today's mistake to this unit.",
                    },
                },
                "required": ["unit_number", "unit_title", "why_relevant"],
            },
            "encouragement": {
                "type": "string",
                "description": "1 short, genuine sentence. Reference something specific from today — not generic.",
            },
        },
        "required": ["top_pattern", "why_it_matters", "exercises", "book_reference", "encouragement"],
    },
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 560px; margin: 0 auto; padding: 20px; color: #1a1a1a; }
  .header { background: #1e3a5f; color: white; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 20px; }
  .header h1 { margin: 0; font-size: 17px; font-weight: 600; }
  .header p  { margin: 4px 0 0; font-size: 13px; opacity: 0.8; }
  .pattern-tag { font-family: monospace; background: #dbeafe; color: #1d4ed8;
                 padding: 2px 8px; border-radius: 4px; font-size: 13px; }
  .why { background: #fff7ed; border-left: 3px solid #f97316;
         padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 14px 0;
         font-size: 14px; line-height: 1.6; }
  h2 { font-size: 14px; font-weight: 600; color: #374151; margin: 20px 0 8px; }
  .exercise { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px;
              padding: 10px 14px; margin: 8px 0; font-size: 14px; line-height: 1.5; }
  .exercise-num { display: inline-block; background: #2563eb; color: white;
                  font-size: 11px; font-weight: 700; width: 18px; height: 18px;
                  border-radius: 50%; text-align: center; line-height: 18px;
                  margin-right: 6px; }
  .book-box { background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px;
              padding: 14px 16px; margin: 18px 0; }
  .book-box .book-title { font-size: 13px; color: #166534; font-weight: 600; margin-bottom: 4px; }
  .book-box .book-unit { font-size: 15px; font-weight: 700; color: #14532d; }
  .book-box .book-why  { font-size: 13px; color: #166534; margin-top: 4px; }
  .encouragement { background: #eff6ff; border-radius: 8px; padding: 12px 16px;
                   font-style: italic; color: #1e40af; font-size: 14px; margin: 16px 0; }
  .footer { font-size: 11px; color: #9ca3af; margin-top: 24px;
            padding-top: 12px; border-top: 1px solid #e5e7eb; }
</style>
</head>
<body>

<div class="header">
  <h1>Today's English Practice — {{ date }}</h1>
  <p>{{ total_mistakes }} mistake{{ 's' if total_mistakes != 1 else '' }} from today's writing</p>
</div>

<p style="font-size:14px;margin:0 0 4px;">Focus pattern: <span class="pattern-tag">{{ top_pattern }}</span></p>

<div class="why">{{ why_it_matters }}</div>

<h2>Practice now (5 minutes)</h2>

{% for ex in exercises %}
<div class="exercise">
  <span class="exercise-num">{{ loop.index }}</span>{{ ex }}
</div>
{% endfor %}

<div class="book-box">
  <div class="book-title">📖 English Grammar in Use — Raymond Murphy</div>
  <div class="book-unit">Unit {{ book_reference.unit_number }}: {{ book_reference.unit_title }}</div>
  <div class="book-why">{{ book_reference.why_relevant }}</div>
</div>

<div class="encouragement">{{ encouragement }}</div>

<div class="footer">
  Generated by your English Learning Agent &mdash; {{ generated_at }}<br>
  <a href="{{ sheet_url }}">View full mistake log →</a>
</div>

</body>
</html>"""


def get_exercise_data(mistakes, date):
    from collections import Counter
    counts = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))
    top_tag = counts.most_common(1)[0][0] if counts else "unknown"

    examples = [m for m in mistakes if m.get("tag") == top_tag][:3]

    summary = {
        "date": date,
        "total_mistakes": len(mistakes),
        "top_tag": top_tag,
        "top_tag_count": counts[top_tag],
        "examples": [
            {"original": m.get("original", ""), "correction": m.get("correction", ""),
             "explanation": m.get("explanation", "")}
            for m in examples
        ],
        "all_tags": dict(counts.most_common(5)),
    }

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        tools=[EXERCISE_TOOL],
        tool_choice={"type": "tool", "name": "submit_exercise"},
        system=(
            "You are an English teacher creating a short, focused daily practice email "
            "for Maahi, an indie iOS developer improving from B1 to B2. "
            "He has a copy of 'English Grammar in Use' by Raymond Murphy (Cambridge). "
            "Reference exact unit numbers and titles from that book — you know them well. "
            "Keep exercises short, specific, and based on his actual mistakes today. "
            "Never be generic. 5 minutes max."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Here are Maahi's mistakes from today ({date}):\n\n"
                f"{json.dumps(summary, indent=2)}\n\n"
                "Generate today's targeted practice using submit_exercise."
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_exercise":
            return block.input

    raise RuntimeError("Claude did not call submit_exercise")


def main():
    parser = argparse.ArgumentParser(description="Compose daily exercise email.")
    parser.add_argument("--mistakes-json", required=True, help="JSON array of today's mistakes")
    parser.add_argument("--date", required=True, help="Date string YYYY-MM-DD")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    mistakes = json.loads(Path(args.mistakes_json).read_text(encoding="utf-8"))
    if not mistakes:
        print("No mistakes today — nothing to send", file=sys.stderr)
        sys.exit(0)

    print(f"Composing exercise for {len(mistakes)} mistakes...", file=sys.stderr)
    data = get_exercise_data(mistakes, args.date)

    sheet_id = os.getenv("GSHEET_MISTAKE_LOG_ID", "")
    html = Template(HTML_TEMPLATE).render(
        date=args.date,
        total_mistakes=len(mistakes),
        top_pattern=data.get("top_pattern", ""),
        why_it_matters=data.get("why_it_matters", ""),
        exercises=data.get("exercises", []),
        book_reference=data.get("book_reference", {"unit_number": "", "unit_title": "", "why_relevant": ""}),
        encouragement=data.get("encouragement", ""),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}",
    )

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"exercise_{args.date}.html"
    out.write_text(html, encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
