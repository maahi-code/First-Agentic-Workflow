#!/usr/bin/env python3
"""
Transcribe a compressed audio file using the Gemini API (google-genai SDK).

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

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp" / "transcripts"
MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-pro"]

TRANSCRIPT_PROMPT = (
    "Transcribe this audio as a raw, unedited transcript. "
    "RULES: "
    "(1) Preserve ALL filler words exactly as spoken — um, uh, like, you know, so, right, hmm. Do NOT remove or clean them up. "
    "(2) Preserve false starts and self-corrections verbatim. If the speaker says 'I... I mean', keep both words. "
    "(3) Mark words you cannot clearly hear or that sound mispronounced as [UNCLEAR]. "
    "(4) Do NOT paraphrase, summarize, or fix grammar. "
    "Output only the transcript text, nothing else."
)


def wait_for_active(client, file_name, max_wait=120):
    for _ in range(max_wait):
        f = client.files.get(name=file_name)
        state = f.state.name if hasattr(f.state, "name") else str(f.state)
        if state == "ACTIVE":
            return f
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {file_name}")
        time.sleep(1)
    raise TimeoutError(f"File {file_name} still not ACTIVE after {max_wait}s")


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio with Gemini.")
    parser.add_argument("--audio-path", required=True, help="Local .mp3 / .opus file to transcribe")
    parser.add_argument("--file-id", help="Source Drive file ID (for tracking in output)")
    parser.add_argument("--model", help="Override Gemini model ID (default: gemini-2.5-flash)")
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

    from google import genai

    client = genai.Client(api_key=api_key)

    size_kb = audio_path.stat().st_size // 1024
    print(f"Uploading {audio_path.name} ({size_kb}KB)...", file=sys.stderr)

    uploaded = client.files.upload(file=audio_path)
    uploaded = wait_for_active(client, uploaded.name)

    models_to_try = [args.model] if args.model else [MODEL] + FALLBACK_MODELS
    transcript = None
    used_model = None
    for m in models_to_try:
        print(f"Transcribing with {m}...", file=sys.stderr)
        try:
            response = client.models.generate_content(
                model=m,
                contents=[TRANSCRIPT_PROMPT, uploaded],
            )
            transcript = response.text.strip()
            used_model = m
            break
        except Exception as e:
            print(f"  {m} failed: {e}", file=sys.stderr)

    if transcript is None:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
        print("All models failed — giving up.", file=sys.stderr)
        sys.exit(1)

    # Clean up uploaded file
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    file_id = args.file_id or audio_path.stem
    result = {
        "text": transcript,
        "file_id": file_id,
        "model": used_model,
        "audio_path": str(audio_path),
    }

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / f"{file_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
