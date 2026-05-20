# Workflow: Daily Speaking Ingest

## Objective
List new speaking videos in Google Drive, transcribe each with Gemini, analyze
the transcript with Claude, and append detected mistakes to the Mistake Log Sheet.

## When to run
Once a day (same time as daily_ingest_writing.md, or after it).

## Prerequisites
- `.env` populated with `GEMINI_API_KEY`, `GDRIVE_VIDEO_FOLDER_ID`, `GSHEET_MISTAKE_LOG_ID`
- `ffmpeg` installed (`brew install ffmpeg`)
- Videos must be in the Drive folder whose ID is in `GDRIVE_VIDEO_FOLDER_ID`

## Tools used (in order)
1. `tools/state_get.py`              — read `last_video_sync`
2. `tools/gdrive_list_videos.py`     — list new videos since that date
3. `tools/gdrive_download_video.py`  — download each video
4. `tools/compress_video_to_audio.py`— strip video, extract 16kHz mono MP3
5. `tools/transcribe_with_gemini.py` — upload audio, get transcript
6. `tools/analyze_text.py`           — analyze transcript (Claude)
7. `tools/sheets_append_mistakes.py` — append mistakes to Sheet
8. `tools/state_set.py`              — advance `last_video_sync`

## Steps

1. **Get last sync date**
   ```bash
   SINCE=$(python tools/state_get.py --key last_video_sync --default 2026-01-01)
   ```

2. **List new videos**
   ```bash
   python tools/gdrive_list_videos.py --since "$SINCE" > .tmp/videos_latest.json
   ```
   If the array is empty, stop here — nothing to process.

3. **For each video in the list:**

   a. Download
   ```bash
   DOWNLOAD=$(python tools/gdrive_download_video.py --file-id <file_id> --name <name>)
   VIDEO_PATH=$(echo "$DOWNLOAD" | python -c "import json,sys; print(json.load(sys.stdin)['local_path'])")
   ```

   b. Compress to audio (~10-100× smaller, cuts Gemini cost proportionally)
   ```bash
   COMPRESS=$(python tools/compress_video_to_audio.py --video-path "$VIDEO_PATH")
   AUDIO_PATH=$(echo "$COMPRESS" | python -c "import json,sys; print(json.load(sys.stdin)['output_path'])")
   ```

   c. Transcribe
   ```bash
   python tools/transcribe_with_gemini.py --audio-path "$AUDIO_PATH" --file-id <file_id> \
     > .tmp/transcript_<file_id>.json
   ```

   d. Analyze transcript
   ```bash
   python tools/analyze_text.py --entry-json .tmp/transcript_<file_id>.json --kind speaking \
     > .tmp/analysis_<file_id>.json
   ```

   e. Append to Sheet
   ```bash
   python tools/sheets_append_mistakes.py --analysis-json .tmp/analysis_<file_id>.json
   ```

   f. Delete local video + audio (keep transcript + analysis)
   ```bash
   rm "$VIDEO_PATH" "$AUDIO_PATH"
   ```

4. **Advance sync date**
   ```bash
   python tools/state_set.py --key last_video_sync --value $(date +%F)
   ```

## Expected output
- New rows with `source=speaking` in the Sheet's `mistakes` tab.
- Local video/audio deleted, transcripts kept in `.tmp/transcripts/`.

## Error handling
- **0 videos**: exit clean.
- **Video > 500MB**: ffmpeg still handles it; Gemini accepts up to 2GB via Files API.
- **Transcription fails**: retry once; if still failing, skip the video and log a warning.
  Do NOT advance the sync date past videos that failed.
- **Garbled transcript** (empty or <10 words): skip analysis, log warning.

## Known gotchas
- The Gemini Files API has a 2GB limit per file and ~50 files stored limit.
  Transcription deletes uploaded files immediately after use so this never accumulates.
- Videos recorded on iPhone are `.mov` (H.264). ffmpeg handles these natively.
- For a video longer than ~30 min, ffmpeg compression still works fine.
  The MP3 output for a 30-min video is ~7MB — well within Gemini limits.
