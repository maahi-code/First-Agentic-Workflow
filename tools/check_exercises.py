#!/usr/bin/env python3
"""
Check exercise answers that the user wrote in a Notion page.

The user writes answers under a heading containing "Exercise" or "Answer"
(e.g. "## Exercise Answers", "## My Answers") in their same-day Notion page.

Reads from .env:
    NOTION_TOKEN
    ANTHROPIC_API_KEY

Usage:
    python tools/check_exercises.py \
        --page-id <notion-page-id> \
        --exercises '["Exercise 1 prompt...", "Exercise 2 prompt..."]' \
        --date 2026-05-20

Output (stdout): JSON
    {
      "found": true,
      "items": [
        {"num": 1, "user_answer": "...", "correct": true, "correction": "", "explanation": "..."},
        ...
      ],
      "overall": "..."
    }
    OR {"found": false} if no exercise answer section was found in the page.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from notion_client import Client

REPO_ROOT = Path(__file__).resolve().parent.parent

TEXT_BLOCK_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "quote", "callout", "to_do",
}
HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}

CHECK_TOOL = {
    "name": "submit_exercise_check",
    "description": "Submit feedback on the user's exercise answers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "num": {"type": "integer", "description": "Exercise number (1-based)"},
                        "user_answer": {"type": "string", "description": "What the user wrote"},
                        "correct": {"type": "boolean"},
                        "correction": {"type": "string", "description": "Corrected version if wrong; empty string if correct"},
                        "explanation": {"type": "string", "description": "1-2 sentences explaining the result"},
                    },
                    "required": ["num", "user_answer", "correct", "correction", "explanation"],
                },
            },
            "overall": {
                "type": "string",
                "description": "1-2 warm but honest sentences summarising how they did overall.",
            },
        },
        "required": ["items", "overall"],
    },
}


def rich_text_to_plain(rich_text):
    return "".join(rt.get("plain_text", "") for rt in rich_text or [])


def fetch_page_blocks(client, page_id):
    blocks = []
    cursor = None
    while True:
        resp = client.blocks.children.list(block_id=page_id, start_cursor=cursor)
        for block in resp.get("results", []):
            btype = block.get("type")
            if btype not in TEXT_BLOCK_TYPES:
                continue
            inner = block.get(btype, {})
            text = rich_text_to_plain(inner.get("rich_text", []))
            blocks.append((btype, text))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return blocks


def extract_exercise_answers(blocks):
    """Return text of blocks that follow an exercise/answer heading."""
    in_section = False
    lines = []
    for btype, text in blocks:
        if btype in HEADING_TYPES:
            lower = text.lower()
            if "exercise" in lower or "answer" in lower or "my answer" in lower:
                in_section = True
            else:
                in_section = False
        elif in_section and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def check_with_claude(exercises, answer_text, date):
    client = anthropic.Anthropic()
    prompt = (
        f"Date: {date}\n\n"
        "Yesterday I gave Maahi these exercises:\n"
        + "\n".join(f"{i+1}. {ex}" for i, ex in enumerate(exercises))
        + f"\n\nHere is what he wrote in his Notion page under the Exercise Answers section:\n\n{answer_text}\n\n"
        "Match each answer to its exercise number (answers are likely in order). "
        "Check correctness and use submit_exercise_check."
    )
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        tools=[CHECK_TOOL],
        tool_choice={"type": "tool", "name": "submit_exercise_check"},
        system=(
            "You are Maahi's English tutor checking his exercise answers. "
            "He is a B1 learner working toward B2. "
            "Be direct: if the answer is correct say so briefly; if wrong give the exact correction. "
            "Never be vague. 1-2 sentences per exercise."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_exercise_check":
            return block.input
    return {"items": [], "overall": "Could not check exercises automatically."}


def main():
    parser = argparse.ArgumentParser(description="Check exercise answers from a Notion page.")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--exercises", required=True, help="JSON array of exercise prompt strings")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("NOTION_TOKEN missing from .env", file=sys.stderr)
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    exercises = json.loads(args.exercises)
    if not exercises:
        print(json.dumps({"found": False}))
        return

    client = Client(auth=token, notion_version="2022-06-28")
    print("Fetching Notion page...", file=sys.stderr)
    blocks = fetch_page_blocks(client, args.page_id)
    answer_text = extract_exercise_answers(blocks)

    if not answer_text.strip():
        print("No exercise answers section found in page.", file=sys.stderr)
        print(json.dumps({"found": False}))
        return

    print(f"Found answers ({len(answer_text)} chars) — checking with Claude...", file=sys.stderr)
    result = check_with_claude(exercises, answer_text, args.date)
    result["found"] = True
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
