#!/usr/bin/env python3
"""
Analyze a speaking practice audio file with Gemini — no transcription.

Gemini listens to the audio directly and gives feedback like a live English tutor:
grammar caught while listening, pronunciation, pacing, filler words, tone, fluency.

Uses gemini-3.5-flash (stable) with fallback to gemini-3.1-flash-lite.
No Claude API needed. One call: audio in → structured JSON out.

Reads from .env:
    GEMINI_API_KEY

Usage:
    python tools/analyze_speaking_with_gemini.py --audio-path .tmp/audio/May4.mp3
    python tools/analyze_speaking_with_gemini.py --audio-path May4.mp3 --file-id abc123

Output (stdout): JSON envelope compatible with gdoc_append_review.py
Also saves to .tmp/speaking_analysis/<file_id>.json
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp" / "speaking_analysis"
PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash"]

ANALYZE_PROMPT = """You are an experienced English speaking coach. Listen carefully to this student's spoken English practice recording.

Your job is to give direct, actionable feedback exactly as a real tutor would — by HEARING the speech, not reading a transcript. Do NOT transcribe the audio.

## What to analyze

1. **Grammar** — errors you hear in the spoken sentences: wrong tense, subject-verb disagreement, missing/wrong articles, wrong prepositions. Quote the exact spoken phrase.
2. **Pronunciation** — specific words or sounds that are mispronounced, swallowed, or unclear. Name the sound and how to fix it.
3. **Pacing** — is the delivery too fast (clarity suffers), too slow (unnatural), or well-paced?
4. **Filler words** — detect and count: um, uh, like, you know, so, right, basically, actually (used as fillers, not meaningful). Excessive = more than once every 10 words.
5. **Tone & confidence** — does the speaker sound confident, hesitant, monotone, or naturally varied?
6. **Fluency** — false starts (beginning a sentence then restarting), long unnatural pauses, excessive self-corrections.

## For each mistake in the `mistakes` array

- `original`: the exact spoken phrase you heard (what the speaker said)
- `correction`: what they should say or do instead
- `mistake_type`: one of `grammar`, `pronunciation`, `naturalness`, `fluency`
- `tag`: a kebab-case pattern slug (2-6 words, NEVER use specific words from the speech). Examples: `subject-verb-agreement-singular`, `excessive-filler-um`, `missing-article-before-noun`, `mispronounced-th-sound`, `too-fast-pacing-loss-of-clarity`, `false-start-pattern`
- `explanation`: 1-3 sentences explaining WHY it's wrong and how to fix it — build the learner's mental model
- `severity`: `high` (blocks comprehension or sounds badly wrong), `medium` (noticeable to a native speaker), `low` (minor)
- `cefr_focus`: e.g. `B1-grammar-subject-verb-agreement`, `B1-speaking-pacing`, `B2-pronunciation-th-sound`

## naturalness_score (1-10)
1-3: Heavy L1 interference, hard to follow | 4-6: B1 learner, understandable but clearly non-native | 7-8: B2, natural with minor touches | 9-10: C1+, feels native

Return ONLY a JSON object with this exact structure:
{
  "mistakes": [...],
  "patterns": ["1-3 cross-cutting observations about recurring speaking habits"],
  "strengths": ["1-3 things the speaker genuinely did well — required, never skip"],
  "naturalness_score": <integer 1-10>,
  "pacing": "good" | "too_fast" | "too_slow",
  "filler_words": ["list of filler words detected, e.g. um, uh"],
  "filler_frequency": "minimal" | "moderate" | "excessive",
  "tone": "confident" | "hesitant" | "monotone" | "varied"
}"""


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


def analyze(client, audio_file, model):
    from google.genai import types
    response = client.models.generate_content(
        model=model,
        contents=[ANALYZE_PROMPT, audio_file],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    raw = response.text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description="Analyze speaking audio directly with Gemini.")
    parser.add_argument("--audio-path", required=True, help="Local .mp3 file to analyze")
    parser.add_argument("--file-id", help="Source Drive file ID (for tracking)")
    parser.add_argument("--model", help="Override Gemini model ID")
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

    models_to_try = [args.model] if args.model else [PRIMARY_MODEL] + FALLBACK_MODELS
    analysis = None
    used_model = None

    for m in models_to_try:
        print(f"Analyzing with {m}...", file=sys.stderr)
        try:
            analysis = analyze(client, uploaded, m)
            used_model = m
            break
        except Exception as e:
            print(f"  {m} failed: {e}", file=sys.stderr)

    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    if analysis is None:
        print("All models failed — giving up.", file=sys.stderr)
        sys.exit(1)

    file_id = args.file_id or audio_path.stem
    result = {
        "file_id": file_id,
        "kind": "speaking",
        "model": used_model,
        "audio_path": str(audio_path),
        "analysis": analysis,
    }

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / f"{file_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
