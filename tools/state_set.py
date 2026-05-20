#!/usr/bin/env python3
"""
Write a key/value into .tmp/state.json. Creates the file (and .tmp/) if missing.

Usage:
    python tools/state_set.py --key last_writing_sync --value 2026-05-19

Prints the written {key, value} pair as JSON to stdout for confirmation.
"""
import argparse
import json
import sys
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / ".tmp" / "state.json"


def main():
    parser = argparse.ArgumentParser(description="Write a key/value into local state.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args()

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("warning: state.json was corrupt, overwriting", file=sys.stderr)

    state[args.key] = args.value
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps({"key": args.key, "value": args.value}))


if __name__ == "__main__":
    main()
