#!/usr/bin/env python3
"""
Extract mono 16kHz MP3 audio from a video file using ffmpeg.

This strips the video track entirely, downsample to 16kHz mono at 32kbps.
A 10-minute .mov (~300MB) becomes ~2-3MB of audio — roughly 100× smaller —
which cuts Gemini transcription cost proportionally.

Requires ffmpeg on PATH (brew install ffmpeg).

Usage:
    python tools/compress_video_to_audio.py --video-path .tmp/videos/day75.mov
    python tools/compress_video_to_audio.py --video-path day75.mov --out-path day75.mp3

Output (stdout): JSON {input_path, output_path, size_before, size_after, ratio}
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp" / "audio"


def check_ffmpeg():
    result = subprocess.run(["which", "ffmpeg"], capture_output=True)
    if result.returncode != 0:
        print("ffmpeg not found. Run: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Strip video → mono 16kHz MP3.")
    parser.add_argument("--video-path", required=True, help="Input video file")
    parser.add_argument("--out-path", help="Output .mp3 path (default: .tmp/audio/<name>.mp3)")
    args = parser.parse_args()

    check_ffmpeg()

    in_path = Path(args.video_path)
    if not in_path.exists():
        print(f"File not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    if args.out_path:
        out_path = Path(args.out_path)
    else:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out_path = TMP_DIR / (in_path.stem + ".mp3")

    cmd = [
        "ffmpeg", "-y",          # overwrite without asking
        "-i", str(in_path),
        "-vn",                    # no video
        "-ar", "16000",           # 16kHz sample rate (speech-optimal)
        "-ac", "1",               # mono
        "-b:a", "32k",            # 32kbps — tiny, fine for speech
        "-f", "mp3",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    size_before = in_path.stat().st_size
    size_after = out_path.stat().st_size
    ratio = round(size_before / size_after, 1) if size_after else 0

    print(json.dumps({
        "input_path": str(in_path),
        "output_path": str(out_path),
        "size_before": size_before,
        "size_after": size_after,
        "ratio": ratio,
    }))


if __name__ == "__main__":
    main()
