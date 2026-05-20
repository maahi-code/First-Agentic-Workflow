#!/usr/bin/env python3
"""
Read a key from .tmp/state.json.

Usage:
    python tools/state_get.py --key last_writing_sync
    python tools/state_get.py --key last_writing_sync --default 2026-01-01

Prints the value to stdout. If the key isn't set and no --default is given,
prints an empty string and exits 0. Only exits non-zero on disk/JSON errors.

State is a flat KV store used by workflows to remember the last sync timestamp
for each pipeline (writing, speaking). It's local-only and regeneratable —
deleting .tmp/state.json just forces a full re-ingest.
"""
import argparse
import json
import sys
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / ".tmp" / "state.json"


def main():
    parser = argparse.ArgumentParser(description="Read a key from local state.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--default", default="")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        print(args.default)
        return

    try:
        state = json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError as exc:
        print(f"state.json is corrupt: {exc}", file=sys.stderr)
        sys.exit(1)

    print(state.get(args.key, args.default))


if __name__ == "__main__":
    main()
