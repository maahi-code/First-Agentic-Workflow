#!/usr/bin/env python3
"""
Analyze one writing or speaking entry with Claude and return structured feedback.

This is the brain of the system. The output schema (enforced via Claude's
tool_use) is what every downstream tool depends on — mistakes have stable
kebab-case tags so recurrence can be counted across weeks/months.

Reads from .env:
    ANTHROPIC_API_KEY

Usage (any one of):
    python tools/analyze_text.py --entry-json .tmp/entry.json --kind writing
    python tools/analyze_text.py --text-file path/to/text.txt --kind writing
    cat text.txt | python tools/analyze_text.py --stdin --kind speaking

Optional:
    --model claude-haiku-4-5-20251001  (default — cheap, fast)
    --model claude-sonnet-4-6          (better explanations, ~5× cost)
    --user-level B1
    --target B2

Output (stdout): a JSON object combining the entry metadata + Claude's analysis.
Also writes the same to .tmp/analysis_<page_id_or_hash>.json.

Output shape:
    {
      "page_id": "...", "title": "...", "text": "...",  # entry metadata if passed
      "kind": "writing",
      "model": "claude-haiku-4-5-20251001",
      "analysis": {
        "mistakes": [
          {"original", "correction", "mistake_type", "tag", "explanation",
           "severity", "cefr_focus"}
        ],
        "patterns": [...],     # high-level observations across the whole entry
        "strengths": [...],    # what Maahi did well
        "naturalness_score": 1-10
      }
    }
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit the structured analysis of one writing/speaking entry.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mistakes": {
                "type": "array",
                "description": "Each detected mistake. Empty array if the entry is clean.",
                "items": {
                    "type": "object",
                    "properties": {
                        "original": {
                            "type": "string",
                            "description": "The exact text from the entry containing the mistake (verbatim quote).",
                        },
                        "correction": {
                            "type": "string",
                            "description": "The corrected version. Minimal edit — fix only what's wrong.",
                        },
                        "mistake_type": {
                            "type": "string",
                            "enum": ["grammar", "vocabulary", "collocation", "pronunciation", "naturalness", "discourse"],
                        },
                        "tag": {
                            "type": "string",
                            "description": "A short kebab-case slug for the underlying PATTERN, not the instance. Used as the recurrence key. Examples: 'redundant-be-with-stative-verb', 'missing-article-with-superlative', 'wrong-preposition-after-depend'. NEVER include specific words from the original.",
                        },
                        "explanation": {
                            "type": "string",
                            "description": "1-3 sentences explaining WHY this is wrong. Focus on building the learner's mental model, not just stating the rule.",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "high = blocks comprehension or sounds badly wrong; medium = noticeable to a native speaker; low = minor style.",
                        },
                        "cefr_focus": {
                            "type": "string",
                            "description": "Which CEFR skill this touches. Format: '<level>-<area>-<sub>'. Examples: 'B2-grammar-stative-verbs', 'B2-vocabulary-collocations', 'B1-grammar-articles'.",
                        },
                    },
                    "required": ["original", "correction", "mistake_type", "tag", "explanation", "severity", "cefr_focus"],
                },
            },
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 high-level patterns across the whole entry (e.g., 'tends to over-use the simple present where present continuous is needed'). Different from individual mistakes — these are cross-cutting observations.",
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 things the learner did well. Required even if the entry has many mistakes — reinforcement matters.",
            },
            "naturalness_score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "How natural the entry sounds to a B2+ native reader. 1-3=heavy L1 translation; 4-6=B1; 7-8=B2; 9-10=C1+.",
            },
        },
        "required": ["mistakes", "patterns", "strengths", "naturalness_score"],
    },
}


def build_system_prompt(user_level, target):
    return f"""You are an experienced English language teacher specialized in helping {user_level} learners reach {target} level.

Your student is Maahi, an indie iOS developer. He's been writing in English daily for 74 days but never reviewing the entries — so the same mistakes repeat unnoticed. Your job is to close that feedback loop with structured, teaching-quality analysis.

## How to analyze

1. Read the entry carefully. Don't rush.
2. Identify mistakes and unnatural patterns. Focus on what will move him from {user_level} → {target}: articles, tenses, prepositions, conditionals, collocations, naturalness, discourse markers.
3. For each mistake, quote the exact original text, give a minimal correction, and explain the WHY in 1-3 sentences — focus on his mental model, not just the rule.

## Tag conventions (critical — these are the recurrence key)

Tags must describe the underlying PATTERN, not the specific instance. They are slugs the system uses to count "you made this same mistake N times this month."

GOOD tags (pattern-level):
- `redundant-be-with-stative-verb` → covers "I am agree", "I am know", "I am think"
- `missing-article-the-with-superlative` → covers "best", "most important"
- `wrong-preposition-after-depend` → depend on/of/from
- `simple-past-instead-of-present-perfect`
- `singular-with-plural-noun-people`
- `comma-splice-instead-of-conjunction`

BAD tags (instance-specific):
- `agree-instead-of-am-agree` ← references specific words
- `mistake-in-day-74` ← references the entry

Use kebab-case, 2-6 words, never include words from the original text.

## What NOT to flag

- Single-keystroke typos with no pattern
- Stylistic choices that work in context
- Informal language if context is informal

## Mistake types

- **grammar**: rules of language (tenses, articles, agreement, prepositions, conditionals)
- **vocabulary**: wrong word choice
- **collocation**: words that don't naturally combine ("make a decision" ✓ vs "do a decision" ✗)
- **pronunciation**: ONLY for speaking transcripts
- **naturalness**: technically correct but sounds non-native
- **discourse**: how ideas connect (transitions, paragraph flow, redundancy)

## Strengths

Always include at least 1 strength — reinforcement matters more than corrections at B1→B2.

## Naturalness score calibration
- 1-3: Heavy L1 translation, hard to read
- 4-6: B1 — understandable but clearly non-native
- 7-8: B2 — natural with occasional non-native touches
- 9-10: C1+ — feels native

Submit your full analysis using the submit_analysis tool. Always include patterns, strengths, and naturalness_score (not just mistakes)."""


def analyze(text, kind, model, user_level, target):
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=build_system_prompt(user_level, target),
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_analysis"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is a {kind} entry from Maahi. Analyze it and submit "
                    f"using the submit_analysis tool.\n\n--- ENTRY ---\n{text}\n--- END ---"
                ),
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_analysis":
            return block.input

    raise RuntimeError("Claude did not call submit_analysis. Response was: " + str(response.content))


def load_input(args):
    """Return (text, meta_dict) from whichever input mode was passed."""
    if args.entry_json:
        entry = json.loads(Path(args.entry_json).read_text(encoding="utf-8"))
        return entry.get("text", ""), entry
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8"), {}
    if args.stdin:
        return sys.stdin.read(), {}
    return None, None


def output_path(meta, text):
    """Pick a stable path under .tmp/ for the analysis dump."""
    page_id = meta.get("page_id")
    if page_id:
        slug = page_id.replace("-", "")[:16]
    else:
        slug = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return TMP_DIR / f"analysis_{slug}.json"


def main():
    parser = argparse.ArgumentParser(description="Analyze one entry with Claude.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--entry-json", help="JSON file (e.g. one element from notion_fetch_writing output)")
    src.add_argument("--text-file", help="Plain text file")
    src.add_argument("--stdin", action="store_true", help="Read text from stdin")

    parser.add_argument("--kind", choices=["writing", "speaking"], default="writing")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    parser.add_argument("--user-level", default="B1")
    parser.add_argument("--target", default="B2")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    text, meta = load_input(args)
    if not text or not text.strip():
        print("No text to analyze (input was empty)", file=sys.stderr)
        sys.exit(1)

    try:
        analysis = analyze(text, args.kind, args.model, args.user_level, args.target)
    except anthropic.APIError as exc:
        print(f"Anthropic API error: {exc}", file=sys.stderr)
        sys.exit(2)

    result = {
        **meta,
        "kind": args.kind,
        "model": args.model,
        "analysis": analysis,
    }

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    output_path(meta, text).write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
