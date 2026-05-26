#!/usr/bin/env python3
"""
Compose the daily email: yesterday's exercise check + today's mistake audit
+ book study plan + today's exercises + Google Doc link.

Reads from .env:
    ANTHROPIC_API_KEY
    GDOC_JOURNAL_ID   (optional — for doc link in email footer)

Usage:
    python tools/compose_daily_exercise.py \
        --mistakes-json .tmp/today_mistakes.json \
        --date 2026-05-20 \
        [--exercise-feedback-json .tmp/exercise_feedback.json] \
        [--doc-url https://docs.google.com/document/d/...]

Input: JSON array of mistake dicts (same shape as analyze_text.py output).
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
                "description": "2-3 short practice prompts based on Maahi's actual mistakes today. Each is one sentence (rewrite exercise or fill-in-the-blank). Tell him to write his answers in today's Notion page under a heading called 'Exercise Answers'.",
                "items": {"type": "string"},
            },
            "book_reference": {
                "type": "object",
                "description": "Exact unit from 'English Grammar in Use' (Raymond Murphy, Cambridge) that covers this pattern.",
                "properties": {
                    "unit_number": {"type": "integer"},
                    "unit_title": {"type": "string", "description": "Exact unit title as in the book."},
                    "why_relevant": {"type": "string", "description": "One sentence connecting today's mistake to this unit."},
                },
                "required": ["unit_number", "unit_title", "why_relevant"],
            },
            "encouragement": {
                "type": "string",
                "description": "1 short, genuine sentence referencing something specific from today — not generic.",
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
         max-width: 580px; margin: 0 auto; padding: 20px; color: #1a1a1a; }
  .header { background: #1e3a5f; color: white; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 20px; }
  .header h1 { margin: 0; font-size: 17px; font-weight: 600; }
  .header p  { margin: 4px 0 0; font-size: 13px; opacity: 0.8; }
  h2 { font-size: 14px; font-weight: 600; color: #374151; margin: 22px 0 8px; text-transform: uppercase; letter-spacing: 0.04em; }
  .section-label { font-size: 11px; font-weight: 700; text-transform: uppercase;
                   letter-spacing: 0.08em; color: #6b7280; margin: 24px 0 8px; }
  /* Exercise feedback */
  .feedback-box { background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px; }
  .feedback-item { margin: 8px 0; font-size: 13px; line-height: 1.6; }
  .feedback-item .label { font-weight: 600; }
  .check { color: #16a34a; }
  .cross { color: #dc2626; }
  .feedback-overall { font-size: 13px; color: #166534; font-style: italic; margin-top: 10px; }
  /* Mistake audit */
  .mistake { background: #fef2f2; border-left: 3px solid #ef4444;
             padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 8px 0; font-size: 13px; line-height: 1.6; }
  .mistake .orig { color: #991b1b; }
  .mistake .corr { color: #166534; font-weight: 600; }
  .mistake .expl { color: #374151; font-size: 12px; margin-top: 3px; }
  /* Book box */
  .book-box { background: #eff6ff; border: 1px solid #93c5fd; border-radius: 8px;
              padding: 14px 16px; margin: 16px 0; }
  .book-box .time { font-size: 12px; font-weight: 700; color: #1d4ed8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .book-box .unit { font-size: 15px; font-weight: 700; color: #1e3a8a; }
  .book-box .why  { font-size: 13px; color: #1d4ed8; margin-top: 4px; }
  .book-box .why-matter { font-size: 13px; color: #374151; margin-top: 6px; font-style: italic; }
  /* Pattern tag */
  .pattern-tag { font-family: monospace; background: #dbeafe; color: #1d4ed8;
                 padding: 2px 8px; border-radius: 4px; font-size: 13px; }
  /* Exercises */
  .exercise { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px;
              padding: 10px 14px; margin: 8px 0; font-size: 14px; line-height: 1.5; }
  .exercise-num { display: inline-block; background: #2563eb; color: white;
                  font-size: 11px; font-weight: 700; width: 18px; height: 18px;
                  border-radius: 50%; text-align: center; line-height: 18px;
                  margin-right: 6px; }
  .notion-hint { background: #fef9c3; border-radius: 6px; padding: 8px 12px;
                 font-size: 12px; color: #713f12; margin-top: 10px; }
  /* Encouragement */
  .encouragement { background: #f5f3ff; border-radius: 8px; padding: 12px 16px;
                   font-style: italic; color: #5b21b6; font-size: 14px; margin: 16px 0; }
  /* Footer */
  .footer { font-size: 11px; color: #9ca3af; margin-top: 24px;
            padding-top: 12px; border-top: 1px solid #e5e7eb; }
  .footer a { color: #2563eb; }
</style>
</head>
<body>

<div class="header">
  <h1>Writing Practice — {{ date }}</h1>
  <p>{{ total_mistakes }} mistake{{ 's' if total_mistakes != 1 else '' }} from yesterday's writing</p>
</div>

{% if exercise_feedback and exercise_feedback.found %}
<div class="section-label">Yesterday's Exercise Check</div>
<div class="feedback-box">
  {% for item in exercise_feedback.items %}
  <div class="feedback-item">
    <span class="label">Exercise {{ item.num }}:</span>
    {% if item.correct %}
      <span class="check">✓ Correct</span> — {{ item.explanation }}
    {% else %}
      <span class="cross">✗</span> You wrote: <em>{{ item.user_answer }}</em><br>
      <span class="corr">→ {{ item.correction }}</span><br>
      <span style="font-size:12px;color:#374151;">{{ item.explanation }}</span>
    {% endif %}
  </div>
  {% endfor %}
  <div class="feedback-overall">{{ exercise_feedback.overall }}</div>
</div>
{% elif exercise_feedback_pending %}
<div class="section-label">Yesterday's Exercise Check</div>
<div style="background:#fef9c3;border-radius:6px;padding:10px 14px;font-size:13px;color:#713f12;margin-bottom:16px;">
  No exercise answers found in yesterday's Notion page. Did you add them under a heading called <strong>Exercise Answers</strong>?
</div>
{% endif %}

<div class="section-label">Today's Mistake Audit</div>
{% for m in mistakes %}
<div class="mistake">
  <span class="orig">✗ "{{ m.original }}"</span><br>
  <span class="corr">✓ "{{ m.correction }}"</span><br>
  <div class="expl">{{ m.explanation }}</div>
</div>
{% endfor %}

<div class="section-label">Today's Study — 30 Minutes</div>
<div class="book-box">
  <div class="time">Open your book now</div>
  <div class="unit">Unit {{ book_reference.unit_number }}: {{ book_reference.unit_title }}</div>
  <div class="why">English Grammar in Use — Raymond Murphy</div>
  <div class="why-matter">{{ book_reference.why_relevant }}</div>
</div>

<div class="section-label">Today's Exercises</div>
<p style="font-size:13px;margin:0 0 10px;color:#374151;">Focus pattern: <span class="pattern-tag">{{ top_pattern }}</span></p>
<p style="font-size:13px;margin:0 0 10px;color:#374151;">{{ why_it_matters }}</p>

{% for ex in exercises %}
<div class="exercise">
  <span class="exercise-num">{{ loop.index }}</span>{{ ex }}
</div>
{% endfor %}

<div class="notion-hint">
  Write your answers in today's Notion page under a heading called <strong>Exercise Answers</strong>. The system will check them tomorrow morning.
</div>

<div class="encouragement">{{ encouragement }}</div>

{% if doc_url %}
<div style="margin: 20px 0;">
  <a href="{{ doc_url }}" style="display:inline-block;background:#1e3a5f;color:#ffffff;padding:11px 22px;border-radius:6px;font-size:14px;font-weight:600;text-decoration:none;">View Your Writing Journal →</a>
</div>
{% endif %}

<div class="footer">
  Generated {{ generated_at }}
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
    parser.add_argument("--mistakes-json", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--exercise-feedback-json", help="JSON file with exercise check result")
    parser.add_argument("--exercise-feedback-pending", action="store_true",
                        help="Set if exercises were sent yesterday but no answers found")
    parser.add_argument("--doc-url", help="Writing Journal Google Doc URL to include in footer")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    mistakes = json.loads(Path(args.mistakes_json).read_text(encoding="utf-8"))
    if not mistakes:
        print("No mistakes today — nothing to send", file=sys.stderr)
        sys.exit(0)

    exercise_feedback = None
    if args.exercise_feedback_json:
        try:
            exercise_feedback = json.loads(Path(args.exercise_feedback_json).read_text())
        except Exception:
            pass

    doc_url = args.doc_url or ""
    if not doc_url:
        doc_id = (os.getenv("GDOC_WRITING_ID", "") or os.getenv("GDOC_JOURNAL_ID", "")).strip()
        if doc_id:
            doc_url = f"https://docs.google.com/document/d/{doc_id}"

    print(f"Composing exercise for {len(mistakes)} writing mistakes...", file=sys.stderr)
    data = get_exercise_data(mistakes, args.date)

    html = Template(HTML_TEMPLATE).render(
        date=args.date,
        total_mistakes=len(mistakes),
        mistakes=mistakes,
        top_pattern=data.get("top_pattern", ""),
        why_it_matters=data.get("why_it_matters", ""),
        exercises=data.get("exercises", []),
        book_reference=data.get("book_reference", {"unit_number": "", "unit_title": "", "why_relevant": ""}),
        encouragement=data.get("encouragement", ""),
        exercise_feedback=exercise_feedback,
        exercise_feedback_pending=args.exercise_feedback_pending,
        doc_url=doc_url,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"exercise_{args.date}.html"
    out.write_text(html, encoding="utf-8")

    # Write sidecar JSON so run_daily.py can save exercises for tomorrow's check
    sidecar = TMP_DIR / f"exercise_data_{args.date}.json"
    sidecar.write_text(json.dumps({
        "exercises": data.get("exercises", []),
        "top_pattern": data.get("top_pattern", ""),
        "book_reference": data.get("book_reference", {}),
    }, ensure_ascii=False))

    print(str(out))


if __name__ == "__main__":
    main()
