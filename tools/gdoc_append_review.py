#!/usr/bin/env python3
"""
Append a tutor-style review to the English Learning Journal Google Doc.

Writing and speaking use SEPARATE docs, created automatically on first run.
Docs use proper Google Docs headings (H1/H2/H3) instead of ASCII art.

Reads from .env:
    ANTHROPIC_API_KEY
    GDOC_WRITING_ID   — auto-created for writing (falls back to GDOC_JOURNAL_ID)
    GDOC_SPEAKING_ID  — auto-created for speaking

Usage:
    python tools/gdoc_append_review.py \
        --mistakes-json .tmp/today_mistakes_writing_2026-05-21.json \
        --date 2026-05-21 \
        --kind writing \
        [--naturalness 7]

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

# ── doc config per kind ───────────────────────────────────────────────────────

DOC_CONFIG = {
    "writing": {
        "env_key": "GDOC_WRITING_ID",
        "fallback_env": "GDOC_JOURNAL_ID",
        "title": "Writing Journal — Maahi",
        "header": "WRITING JOURNAL\nMaahi — B1 → B2 by December 2026",
        "state_file": "gdoc_writing_state.json",
    },
    "speaking": {
        "env_key": "GDOC_SPEAKING_ID",
        "fallback_env": None,
        "title": "Speaking Journal — Maahi",
        "header": "SPEAKING JOURNAL\nMaahi — B1 → B2 by December 2026",
        "state_file": "gdoc_speaking_state.json",
    },
    "weekly": {
        "env_key": "GDOC_WRITING_ID",
        "fallback_env": "GDOC_JOURNAL_ID",
        "title": "Writing Journal — Maahi",
        "header": "WRITING JOURNAL\nMaahi — B1 → B2 by December 2026",
        "state_file": "gdoc_writing_state.json",
    },
}

# ── tutor comment (Claude) ────────────────────────────────────────────────────

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
        "focus_for_tomorrow": "Review your top recurring pattern.",
    }


# ── DocBuilder — tracks indices for Google Docs batchUpdate ──────────────────

class DocBuilder:
    """
    Builds a sequence of Google Docs API requests while tracking the running
    character index so paragraph styles are applied to the correct ranges.

    All paragraph inserts include a trailing \\n.  The updateParagraphStyle
    range covers [start, start + len(text) + 1) — which includes the \\n,
    required by the Docs API for the style to take effect.
    """

    def __init__(self, start_index: int):
        self.pos = start_index
        self.requests: list = []

    # ── internal helpers ──────────────────────────────────────────────────────

    def _insert(self, text: str):
        self.requests.append({
            "insertText": {
                "location": {"index": self.pos},
                "text": text,
            }
        })
        self.pos += len(text)

    def _para_style(self, start: int, end: int, named_style: str):
        self.requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named_style},
                "fields": "namedStyleType",
            }
        })

    def _bold(self, start: int, end: int, bold: bool = True):
        self.requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"bold": bold},
                "fields": "bold",
            }
        })

    # ── public API ────────────────────────────────────────────────────────────

    def h1(self, text: str):
        """Insert a HEADING_1 paragraph."""
        start = self.pos
        self._insert(text + "\n")
        self._para_style(start, self.pos, "HEADING_1")
        return self

    def h2(self, text: str):
        """Insert a HEADING_2 paragraph."""
        start = self.pos
        self._insert(text + "\n")
        self._para_style(start, self.pos, "HEADING_2")
        return self

    def h3(self, text: str):
        """Insert a HEADING_3 paragraph."""
        start = self.pos
        self._insert(text + "\n")
        self._para_style(start, self.pos, "HEADING_3")
        return self

    def p(self, text: str):
        """Insert a NORMAL_TEXT paragraph."""
        self._insert(text + "\n")
        return self

    def p_bold(self, text: str):
        """Insert a bold NORMAL_TEXT paragraph."""
        start = self.pos
        self._insert(text + "\n")
        self._bold(start, self.pos)
        return self

    def blank(self):
        """Insert an empty paragraph (visual breathing room)."""
        self._insert("\n")
        return self


# ── Google Doc helpers ────────────────────────────────────────────────────────

def get_or_create_doc(service, kind):
    cfg = DOC_CONFIG.get(kind, DOC_CONFIG["writing"])
    doc_id = os.getenv(cfg["env_key"], "").strip()

    # Backward compat: fall back to GDOC_JOURNAL_ID for writing
    if not doc_id and cfg.get("fallback_env"):
        doc_id = os.getenv(cfg["fallback_env"], "").strip()

    if doc_id:
        try:
            service.documents().get(documentId=doc_id).execute()
            return doc_id
        except Exception:
            print(f"Stored doc ID not accessible — creating a new {kind} doc.", file=sys.stderr)

    print(f"Creating {cfg['title']}...", file=sys.stderr)
    doc = service.documents().create(body={"title": cfg["title"]}).execute()
    doc_id = doc["documentId"]

    # Write a clean document header
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [
            {"insertText": {
                "location": {"index": 1},
                "text": cfg["header"] + "\n\n",
            }}
        ]},
    ).execute()

    set_key(str(ENV_PATH), cfg["env_key"], doc_id)
    print(f"  Saved {cfg['env_key']}={doc_id} to .env", file=sys.stderr)
    return doc_id


def get_end_index(service, doc_id):
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    end = 1
    for el in content:
        end = el.get("endIndex", end)
    return end - 1  # insert before the implicit trailing newline


# ── state helpers ─────────────────────────────────────────────────────────────

def load_state(kind):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DOC_CONFIG.get(kind, DOC_CONFIG["writing"])
    path = STATE_DIR / cfg["state_file"]
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_state(kind, state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DOC_CONFIG.get(kind, DOC_CONFIG["writing"])
    (STATE_DIR / cfg["state_file"]).write_text(json.dumps(state, indent=2))


# ── date helpers ──────────────────────────────────────────────────────────────

def format_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        return date_str


def get_week_key(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    except ValueError:
        return None


def get_week_range_str(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        if monday.month == sunday.month:
            return f"{monday.strftime('%b %d')} – {sunday.strftime('%d, %Y')}"
        return f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"
    except ValueError:
        return date_str


# ── content builders ──────────────────────────────────────────────────────────

def build_week_header(builder, date_str, mistake_count, prev_count):
    """Insert a week divider heading."""
    week_key = get_week_key(date_str)
    week_range = get_week_range_str(date_str)

    trend = ""
    if prev_count and mistake_count:
        diff = mistake_count - prev_count
        if diff < 0:
            trend = f"  ↓ {abs(diff)} fewer than last week 🎉"
        elif diff > 0:
            trend = f"  ↑ {diff} more than last week"
        else:
            trend = "  Same count as last week"

    builder.blank()
    builder.h3(f"Week {week_key}  ·  {week_range}{trend}")


def build_daily_entry(builder, date_str, mistakes, tutor, kind, naturalness=None):
    """Insert a full day's entry into the builder."""
    by_tag = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))

    # Day title
    title = f"{format_date(date_str)} — {kind.capitalize()} Review"
    builder.h1(title)

    # Summary line
    summary = f"{len(mistakes)} mistake{'s' if len(mistakes) != 1 else ''}"
    if naturalness:
        summary += f"  ·  Naturalness: {naturalness}/10"
    builder.p(summary)
    builder.blank()

    # Mistakes
    if mistakes:
        builder.h2("Mistakes")
        for i, m in enumerate(mistakes, 1):
            orig = m.get("original", "").strip()
            corr = m.get("correction", "").strip()
            expl = m.get("explanation", "").strip()
            cefr = m.get("cefr_focus", "").strip()
            severity = m.get("severity", "").strip()

            builder.p_bold(f'{i}.  ✗  "{orig}"')
            builder.p(f'       ✓  "{corr}"')
            if expl:
                builder.p(f"       {expl}")
            meta = "  ·  ".join(filter(None, [cefr, severity]))
            if meta:
                builder.p(f"       [{meta}]")
            builder.blank()

    # Top patterns
    if by_tag:
        builder.h2("Top Patterns Today")
        for tag, count in by_tag.most_common(5):
            builder.p(f"  •  {tag}   ×{count}")
        builder.blank()

    # Tutor comment
    builder.h2("Tutor Comment")
    builder.blank()
    builder.p(tutor.get("overall_comment", ""))
    builder.blank()
    builder.p_bold(f"Tomorrow:  {tutor.get('focus_for_tomorrow', '')}")
    builder.blank()
    builder.blank()


def build_weekly_entry(builder, date_since, date_until, mistakes):
    """Insert a weekly summary into the builder."""
    by_tag = Counter(m.get("tag", "") for m in mistakes if m.get("tag"))
    by_type = Counter(m.get("mistake_type", "") for m in mistakes if m.get("mistake_type"))
    by_sev = Counter(m.get("severity", "") for m in mistakes if m.get("severity"))
    days = len({m.get("date", "") for m in mistakes if m.get("date")})

    builder.h1(f"Weekly Summary  ·  {date_since}  →  {date_until}")
    builder.p(f"Days with practice: {days}   ·   Total mistakes: {len(mistakes)}")
    builder.blank()

    if by_type:
        builder.h2("Breakdown by Type")
        for t, c in by_type.most_common():
            builder.p(f"  {t:<20}  {c}")
        builder.blank()

    if by_sev:
        builder.h2("Severity Split")
        for s, c in by_sev.most_common():
            builder.p(f"  {s:<20}  {c}")
        builder.blank()

    if by_tag:
        builder.h2("Top Recurring Patterns This Week")
        for tag, count in by_tag.most_common(8):
            builder.p(f"  •  {tag}   ×{count}")
        builder.blank()

    builder.blank()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Append review to learning journal doc.")
    parser.add_argument("--mistakes-json", required=True)
    parser.add_argument("--date", required=True,
                        help="YYYY-MM-DD, or YYYY-MM-DD:YYYY-MM-DD for weekly range")
    parser.add_argument("--kind", default="writing",
                        choices=["writing", "speaking", "weekly"])
    parser.add_argument("--naturalness", type=int, default=None,
                        help="Average naturalness score (1-10) to show in the day header")
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

    print(f"Locating {args.kind} doc...", file=sys.stderr)
    doc_id = get_or_create_doc(service, args.kind)

    state = load_state(args.kind)
    end_index = get_end_index(service, doc_id)
    builder = DocBuilder(end_index)

    if args.kind == "weekly":
        parts = args.date.split(":")
        since = parts[0]
        until = parts[1] if len(parts) > 1 else parts[0]
        build_weekly_entry(builder, since, until, mistakes)
        state["prev_week_count"] = len(mistakes)
        state["prev_week_key"] = get_week_key(since)
        save_state(args.kind, state)

    else:
        # Week header when crossing into a new week
        current_week = get_week_key(args.date)
        last_week = state.get("last_doc_week")
        if current_week and current_week != last_week:
            prev_count = state.get("prev_week_count", 0)
            build_week_header(builder, args.date, len(mistakes), prev_count)
            state["last_doc_week"] = current_week

        print(f"Generating tutor comment for {len(mistakes)} mistakes...", file=sys.stderr)
        tutor = generate_tutor_comment(mistakes, args.date, args.kind)
        build_daily_entry(builder, args.date, mistakes, tutor, args.kind, args.naturalness)
        save_state(args.kind, state)

    print(f"Appending {len(builder.requests)} formatting requests to doc...", file=sys.stderr)
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": builder.requests},
    ).execute()

    doc_url = f"https://docs.google.com/document/d/{doc_id}"
    print(f"  Done: {doc_url}", file=sys.stderr)
    print(json.dumps({"doc_url": doc_url, "mistakes": len(mistakes)}))


if __name__ == "__main__":
    main()
