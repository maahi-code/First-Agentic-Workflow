#!/usr/bin/env python3
"""
Append a tutor-style review to the English Learning Journal Google Doc.

Creates the doc on first run and saves GDOC_JOURNAL_ID to .env.

Reads from .env:
    ANTHROPIC_API_KEY
    GDOC_JOURNAL_ID      (auto-created on first run)

Usage:
    python tools/gdoc_append_review.py \
        --mistakes-json .tmp/today_mistakes_2026-05-20.json \
        --date 2026-05-20 \
        [--kind writing|speaking|weekly]

Output (stdout): JSON {"doc_url": "...", "mistakes": N}
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv, set_key
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _google_auth import get_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
STATE_DIR = REPO_ROOT / ".tmp" / "state"

TUTOR_TOOL = {
    "name": "submit_tutor_comment",
    "description": "Submit a personalised tutor comment for today's review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_comment": {
                "type": "string",
                "description": (
                    "3-5 sentences. Start with one genuine observation about what they "
                    "did well today. Then name the main pattern they need to fix and "
                    "explain exactly why it matters for B2 fluency. End with one "
                    "concrete tip they can apply tomorrow. Warm but honest. No fluff."
                ),
            },
            "focus_for_tomorrow": {
                "type": "string",
                "description": (
                    "One short sentence: the single most important thing to practise "
                    "tomorrow based on today's mistakes."
                ),
            },
        },
        "required": ["overall_comment", "focus_for_tomorrow"],
    },
}


# ── tutor comment ─────────────────────────────────────────────────────────────

def generate_tutor_comment(mistakes, date, kind):
    by_tag = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))
    by_type = Counter(m.get("mistake_type", "") for m in mistakes if m.get("mistake_type"))
    by_sev = Counter(m.get("severity", "") for m in mistakes if m.get("severity"))

    top_examples = []
    if by_tag:
        top_tag = by_tag.most_common(1)[0][0]
        for m in mistakes:
            if m.get("tag") == top_tag and len(top_examples) < 3:
                top_examples.append({
                    "original": m.get("original", ""),
                    "correction": m.get("correction", ""),
                })

    summary = {
        "date": date,
        "kind": kind,
        "total_mistakes": len(mistakes),
        "by_type": dict(by_type.most_common()),
        "top_patterns": dict(by_tag.most_common(5)),
        "severity_split": dict(by_sev),
        "top_pattern_examples": top_examples,
    }

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        tools=[TUTOR_TOOL],
        tool_choice={"type": "tool", "name": "submit_tutor_comment"},
        system=(
            "You are Maahi's personal English tutor. He is an indie iOS developer "
            "improving from B1 to B2 English by December 2026. "
            "You review his daily writing or speaking practice. "
            "Your comments go directly into his private learning journal — "
            "be direct, specific, and genuinely helpful. Never be generic."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Here is today's mistake summary ({date}, {kind}):\n\n"
                f"{json.dumps(summary, indent=2)}\n\n"
                "Write a tutor comment using submit_tutor_comment."
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_tutor_comment":
            return block.input

    return {
        "overall_comment": "Keep practising — consistency is the key to B2.",
        "focus_for_tomorrow": "Review subject-verb agreement.",
    }


# ── doc helpers ───────────────────────────────────────────────────────────────

def get_or_create_doc(service):
    doc_id = os.getenv("GDOC_JOURNAL_ID", "").strip()
    if doc_id:
        try:
            service.documents().get(documentId=doc_id).execute()
            return doc_id
        except Exception:
            print("Stored GDOC_JOURNAL_ID not found — creating a new doc.", file=sys.stderr)

    print("Creating English Learning Journal doc...", file=sys.stderr)
    doc = service.documents().create(
        body={"title": "English Learning Journal — Maahi"}
    ).execute()
    doc_id = doc["documentId"]

    # Write the journal header
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [
            {"insertText": {
                "location": {"index": 1},
                "text": (
                    "ENGLISH LEARNING JOURNAL\n"
                    "Maahi — B1 → B2 by December 2026\n"
                    "────────────────────────────────────────────────────\n\n"
                ),
            }}
        ]},
    ).execute()

    set_key(str(ENV_PATH), "GDOC_JOURNAL_ID", doc_id)
    print(f"  Saved GDOC_JOURNAL_ID={doc_id} to .env", file=sys.stderr)
    return doc_id


def get_end_index(service, doc_id):
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    end = 1
    for el in content:
        end = el.get("endIndex", end)
    return end - 1  # insert before the implicit trailing newline


# ── text builder ──────────────────────────────────────────────────────────────

def format_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        return date_str


def get_week_key(date_str):
    """Return ISO week key like '2026-W20' for a given date string."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    except ValueError:
        return None


def get_week_range_str(date_str):
    """Return 'Mon DD – Sun DD Mon YYYY' for the week containing date_str."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        if monday.month == sunday.month:
            return f"{monday.strftime('%b %d')} – {sunday.strftime('%d, %Y')}"
        return f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"
    except ValueError:
        return date_str


def load_doc_state():
    """Load persistent doc state (last week written, previous week mistake count)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / "gdoc_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {}


def save_doc_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "gdoc_state.json").write_text(json.dumps(state, indent=2))


def build_week_header(date_str, current_count, prev_count):
    """Build a week separator block to insert at the start of a new week."""
    wide = "█" * 52
    week_key = get_week_key(date_str)
    week_range = get_week_range_str(date_str)

    trend = ""
    if prev_count and current_count:
        diff = current_count - prev_count
        if diff < 0:
            trend = f"  ↓{abs(diff)} fewer than last week 🎉"
        elif diff > 0:
            trend = f"  ↑{diff} more than last week"
        else:
            trend = "  Same as last week"

    lines = [
        "\n\n" + wide,
        f"  WEEK  {week_key}  |  {week_range}",
        wide + "\n",
    ]
    return "\n".join(lines)


def build_daily_text(date_str, mistakes, tutor, kind):
    by_tag = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))
    lines = []
    sep = "─" * 52
    wide = "═" * 52

    lines += [
        "\n" + wide,
        f"📅  {format_date(date_str)}  —  {kind.capitalize()} Review",
        wide + "\n",
        f"{len(mistakes)} mistake{'s' if len(mistakes) != 1 else ''} found\n",
    ]

    for i, m in enumerate(mistakes, 1):
        original = m.get("original", "").strip()
        correction = m.get("correction", "").strip()
        explanation = m.get("explanation", "").strip()
        cefr = m.get("cefr_focus", "").strip()
        severity = m.get("severity", "").strip()

        lines.append(f"{i}.  ✗  \"{original}\"")
        lines.append(f"    ✓  \"{correction}\"")
        if explanation:
            lines.append(f"    →  {explanation}")
        meta = " · ".join(filter(None, [cefr, severity]))
        if meta:
            lines.append(f"    [{meta}]")
        lines.append("")

    if by_tag:
        lines += [sep, "TOP PATTERNS TODAY"]
        for tag, count in by_tag.most_common(5):
            lines.append(f"  •  {tag}  ×{count}")
        lines.append("")

    lines += [
        sep,
        "💬  TUTOR COMMENT",
        "",
        tutor.get("overall_comment", ""),
        "",
        f"▶  Tomorrow:  {tutor.get('focus_for_tomorrow', '')}",
        "\n",
    ]

    return "\n".join(lines)


def build_weekly_text(date_since, date_until, mistakes):
    by_tag = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))
    by_type = Counter(m.get("mistake_type", "") for m in mistakes if m.get("mistake_type"))
    by_sev = Counter(m.get("severity", "") for m in mistakes if m.get("severity"))
    dates = len({m.get("date", "") for m in mistakes if m.get("date")})
    wide = "═" * 52
    sep = "─" * 52

    lines = [
        "\n" + wide,
        f"📊  WEEKLY SUMMARY  —  {date_since} → {date_until}",
        wide + "\n",
        f"Days with practice:  {dates}",
        f"Total mistakes:      {len(mistakes)}",
        "",
    ]

    if by_type:
        lines.append("Breakdown by type:")
        for t, c in by_type.most_common():
            lines.append(f"  {t:<18}  {c}")
        lines.append("")

    if by_sev:
        lines.append("Severity split:")
        for s, c in by_sev.most_common():
            lines.append(f"  {s:<18}  {c}")
        lines.append("")

    if by_tag:
        lines += [sep, "TOP RECURRING PATTERNS THIS WEEK"]
        for tag, count in by_tag.most_common(8):
            lines.append(f"  •  {tag}  ×{count}")
        lines.append("")

    lines.append(sep + "\n")
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Append review to English Learning Journal doc.")
    parser.add_argument("--mistakes-json", required=True,
                        help="JSON array of mistake dicts (same shape as mistakes tab)")
    parser.add_argument("--date", required=True, help="Date YYYY-MM-DD (or YYYY-MM-DD:YYYY-MM-DD for weekly)")
    parser.add_argument("--kind", default="writing",
                        choices=["writing", "speaking", "weekly"],
                        help="Type of review")
    args = parser.parse_args()

    load_dotenv(ENV_PATH, override=True)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    mistakes = json.loads(Path(args.mistakes_json).read_text(encoding="utf-8"))
    if not mistakes:
        print("No mistakes — nothing to write.", file=sys.stderr)
        print(json.dumps({"doc_url": "", "mistakes": 0}))
        return

    try:
        creds = get_credentials()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    service = build("docs", "v1", credentials=creds)

    print("Locating journal doc...", file=sys.stderr)
    doc_id = get_or_create_doc(service)

    state = load_doc_state()

    if args.kind == "weekly":
        parts = args.date.split(":")
        since = parts[0]
        until = parts[1] if len(parts) > 1 else parts[0]
        text = build_weekly_text(since, until, mistakes)
        # Track mistake count for this week so next week can show trend
        state["prev_week_count"] = len(mistakes)
        state["prev_week_key"] = get_week_key(since)
        save_doc_state(state)
    else:
        # Check if we crossed into a new week — if so, prepend a week header
        current_week = get_week_key(args.date)
        last_week = state.get("last_doc_week")
        week_prefix = ""
        if current_week and current_week != last_week:
            prev_count = state.get("prev_week_count", 0)
            week_prefix = build_week_header(args.date, len(mistakes), prev_count)
            state["last_doc_week"] = current_week

        print(f"Generating tutor comment for {len(mistakes)} mistakes...", file=sys.stderr)
        tutor = generate_tutor_comment(mistakes, args.date, args.kind)
        text = week_prefix + build_daily_text(args.date, mistakes, tutor, args.kind)
        save_doc_state(state)

    print("Appending to doc...", file=sys.stderr)
    end_index = get_end_index(service, doc_id)
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": end_index}, "text": text}}]},
    ).execute()

    doc_url = f"https://docs.google.com/document/d/{doc_id}"
    print(f"  Done: {doc_url}", file=sys.stderr)
    print(json.dumps({"doc_url": doc_url, "mistakes": len(mistakes)}))


if __name__ == "__main__":
    main()
