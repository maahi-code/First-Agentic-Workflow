# Workflow: Daily Writing Ingest

## Objective
Pull new entries from the Notion "Daily Writing Practice" database, analyze each
with Claude, and append the detected mistakes to the Mistake Log Google Sheet.

## When to run
Once a day (or manually). Safe to run more than once a day, but see the
same-day caveat under "Known gotchas".

## Prerequisites
- `.env` populated (run `python setup.py` once if not).
- `NOTION_TOKEN`, `NOTION_WRITING_DB_ID`, `ANTHROPIC_API_KEY`, `GSHEET_MISTAKE_LOG_ID`.

## Tools used (in order)
1. `tools/state_get.py`        — read `last_writing_sync`
2. `tools/notion_fetch_writing.py` — fetch entries since that date
3. `tools/analyze_text.py`     — analyze each entry (Claude)
4. `tools/sheets_append_mistakes.py` — append mistakes to the Sheet
5. `tools/state_set.py`        — advance `last_writing_sync`

## Steps

1. **Get last sync date**
   ```bash
   SINCE=$(python tools/state_get.py --key last_writing_sync --default 2026-01-01)
   ```

2. **Fetch new entries**
   ```bash
   python tools/notion_fetch_writing.py --since "$SINCE" > .tmp/writing_latest.json
   ```
   If the array is empty, stop here — there's nothing new. Do **not** advance the
   sync date (so a later entry on the same boundary isn't skipped).

3. **Analyze + append each entry**
   For each element of the array, pipe analysis straight into the Sheet:
   ```bash
   python tools/analyze_text.py --entry-json <entry>.json --kind writing \
     | python tools/sheets_append_mistakes.py --stdin
   ```
   `analyze_text.py` also auto-saves `.tmp/analysis_<page_id>.json` for inspection.

4. **Advance the sync date** (only after all entries succeeded)
   ```bash
   python tools/state_set.py --key last_writing_sync --value $(date +%F)
   ```

## Expected output
- New rows in the Sheet's `mistakes` tab (one per mistake found).
- `last_writing_sync` updated to today.

## Error handling
- **0 entries**: exit clean, leave the sync date untouched.
- **Claude rate-limit / timeout**: retry that one entry once. If it still fails,
  skip it and do NOT advance the sync date past it (so it's retried next run).
- **Empty `text` on an entry**: skip silently (a day with no writing).
- **Sheet append fails**: stop; the sync date stays put so nothing is lost.

## Known gotchas
- **Same-day re-runs can duplicate.** Entries are filtered by `created_time >= since`,
  and the sync date is stored at day granularity. If you write and run twice in one
  day, today's entries may be appended twice. For a once-a-day cron this never happens.
  A future `sheets_query_mistakes` (M7) can dedupe by `source_ref` if this becomes a problem.
- `created_time` is stable across edits, so editing an old entry won't re-ingest it.
