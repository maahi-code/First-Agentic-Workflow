#!/usr/bin/env python3
"""
Transcribe a compressed audio file using the Gemini API.

Uploads the audio to the Gemini Files API, requests a transcript, then deletes
the uploaded file (to avoid storage accumulation). Works well for multilingual
speech — Maahi's Indian-accented English transcribes more accurately here than
with Whisper's English-only model.

Reads from .env:
    GEMINI_API_KEY

Usage:
    python tools/transcribe_with_gemini.py --audio-path .tmp/audio/day75.mp3
    python tools/transcribe_with_gemini.py --audio-path day75.mp3 --file-id abc123

Output (stdout): JSON {text, file_id, model, audio_path}
Also saves to .tmp/transcripts/<file_id>.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp" / "transcripts"
MODEL = "gemini-2.0-flash"
TRANSCRIPT_PROMPT = (
    "Transcribe every word spoken in this audio exactly as heard. "
    "Include all words — do not summarize, paraphrase, or skip repetitions. "
    "Output only the transcript text, nothing else."
)


def wait_for_file_active(uploaded_file, max_wait=60):
    """Gemini Files API: wait until the uploaded file is ready for inference."""
    for _ in range(max_wait):
        f = genai.get_file(uploaded_file.name)
        if f.state.name == "ACTIVE":
            return f
        if f.state.name == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {f.name}")
        time.sleep(1)
    raise TimeoutError(f"File {uploaded_file.name} still not ACTIVE after {max_wait}s")


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio with Gemini.")
    parser.add_argument("--audio-path", required=True, help="Local .mp3 / .opus file to transcribe")
    parser.add_argument("--file-id", help="Source Drive file ID (for tracking in output)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    audio_path = Path(args.audio_path)
    if not audio_path.exists():
        print(f"File not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    genai.configure(api_key=api_key)

    print(f"Uploading {audio_path.name} ({audio_path.stat().st_size // 1024}KB)...", file=sys.stderr)
    uploaded = genai.upload_file(path=str(audio_path), display_name=audio_path.name)
    uploaded = wait_for_file_active(uploaded)

    model = genai.GenerativeModel(MODEL)
    response = model.generate_content([TRANSCRIPT_PROMPT, uploaded])
    transcript = response.text.strip()

    # Clean up uploaded file to avoid storage accumulation
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    file_id = args.file_id or audio_path.stem
    result = {
        "text": transcript,
        "file_id": file_id,
        "model": MODEL,
        "audio_path": str(audio_path),
    }

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / f"{file_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
