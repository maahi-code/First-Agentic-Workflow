# Workflow: Daily Writing Ingest

## Objective
Pull new entries from the Notion "Daily Writing Practice" database, analyze each
with Claude, send a feedback email with exercises and the Google Doc link, and
append mistakes to the rolling 90-day history for the weekly report.

## When to run
Every morning at 08:00 via launchd (`com.maahi.english-daily.plist`). Safe to run
manually at any time — already-processed pages are skipped automatically.

## Prerequisites
- `.env` populated: `NOTION_TOKEN`, `NOTION_WRITING_DB_ID`, `ANTHROPIC_API_KEY`,
  `REPORT_TO_EMAIL`, `GDOC_WRITING_ID` (or `GDOC_JOURNAL_ID`)
- `token.json` present (Google OAuth — run `python setup.py` once)

## Tools used (in order)
1. `tools/state_get.py`             — read `last_writing_sync`
2. `tools/notion_fetch_writing.py`  — fetch entries since that date (IST midnight filter)
3. `.tmp/state/processed_pages.json` — skip already-processed page IDs
4. `tools/analyze_text.py`          — analyze each entry with Claude (Haiku)
5. `tools/gdoc_append_review.py`    — append mistakes + tutor comment to Writing Journal doc
6. `tools/compose_daily_exercise.py` — compose HTML email (mistakes + exercises + doc link)
7. `tools/send_gmail_report.py`     — send the email via Gmail API
8. `tools/state_set.py`             — advance `last_writing_sync`
9. `.tmp/state/mistakes_history.json` — append mistakes for weekly report

## Steps

1. **Get last sync date**
   ```bash
   SINCE=$(python tools/state_get.py --key last_writing_sync --default 2026-01-01)
   ```

2. **Fetch new entries**
   ```bash
   python tools/notion_fetch_writing.py --since "$SINCE" > .tmp/writing_latest.json
   ```
   Uses IST midnight (`+05:30`) as the filter boundary so entries written after
   midnight IST (which land on the previous UTC date) are always captured.

   If the array is empty → send a reminder email and stop. Do **not** advance the
   sync date.

3. **Skip already-processed pages**
   Check `.tmp/state/processed_pages.json`. Any `page_id` already in that set is
   skipped. This prevents duplicate emails on re-runs or timezone edge cases.

4. **Analyze each entry**
   ```bash
   python tools/analyze_text.py --entry-json .tmp/entry_daily_00.json --kind writing
   ```
   Returns structured JSON: `mistakes[]`, `patterns[]`, `strengths[]`,
   `naturalness_score`. If any entry fails, stop — do NOT advance sync date.

5. **Append to Writing Journal Google Doc**
   ```bash
   python tools/gdoc_append_review.py \
     --mistakes-json .tmp/today_mistakes_writing_<date>.json \
     --date <date> --kind writing [--naturalness <score>]
   ```
   Auto-creates the doc on first run and saves `GDOC_WRITING_ID` to `.env`.
   Returns `{"doc_url": "..."}` used in the email.

6. **Compose and send the email**
   ```bash
   python tools/compose_daily_exercise.py \
     --mistakes-json .tmp/today_mistakes_writing_<date>.json \
     --date <date> --doc-url <url>
   python tools/send_gmail_report.py --html-file .tmp/exercise_<date>.html \
     --subject "Writing Practice — <date> (<N> mistakes)"
   ```
   Email contains: yesterday's exercise check, today's mistakes, book unit, new
   exercises, and a **View Your Writing Journal** button.

7. **Advance state**
   ```bash
   python tools/state_set.py --key last_writing_sync --value $(date +%F)
   ```
   Also: saves processed `page_id`s, appends mistakes to `mistakes_history.json`.

## Expected output
- Email in ms4341547@gmail.com with mistakes, exercises, and Journal link.
- New entry in Writing Journal Google Doc.
- `last_writing_sync` updated to today.
- Mistakes appended to `.tmp/state/mistakes_history.json` (feeds weekly report).

## Error handling
- **0 new entries**: send reminder email, leave sync date untouched.
- **All entries already processed**: send reminder email, no analysis.
- **Claude fails on one entry**: skip it, do NOT advance sync date (retried tomorrow).
- **Google Doc append fails**: log error, fall back to env-var doc URL in email.
- **Gmail send fails**: log error, HTML saved in `.tmp/` for manual send.

## Known gotchas
- `created_time` in Notion is UTC. Entries written after midnight IST (e.g. 12:30 AM)
  have a UTC timestamp on the previous calendar day. The IST midnight filter handles
  this — use `+05:30` offset, not `Z`, in `notion_fetch_writing.py`.
- Re-runs are safe: `processed_pages.json` prevents double-sending.
- `created_time` is stable across edits — editing an old entry never re-ingests it.
