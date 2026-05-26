# Workflow: Weekly Progress Report

## Objective
Every Sunday, summarize the past 7 days of mistakes, compose an HTML progress email
with Claude, send it, and append a weekly summary to the Writing Journal Google Doc.

## When to run
Every Sunday at 19:00 via launchd (`com.maahi.english-weekly.plist`).
Can be triggered manually: `python run_weekly.py`

## Prerequisites
- At least one week of daily runs so `.tmp/state/mistakes_history.json` has data
- `ANTHROPIC_API_KEY`, `REPORT_TO_EMAIL` in `.env`
- `token.json` present (Google OAuth)

## Data source
`run_daily.py` appends every mistake to `.tmp/state/mistakes_history.json` after
each successful analysis. This is a flat JSON array of mistake objects, each with:
`date`, `page_id`, `tag`, `original`, `correction`, `severity`, `cefr_focus`, etc.
The file is capped at 90 days of history.

## Tools used (in order)
1. `.tmp/state/mistakes_history.json` — filter to past 7 days
2. `tools/compose_weekly_report.py`   — Claude summarizes + renders HTML email
3. `tools/send_gmail_report.py`       — sends the email via Gmail API
4. `tools/gdoc_append_review.py`      — appends weekly summary to Writing Journal doc

## Steps

1. **Filter past 7 days from history**
   ```python
   week_mistakes = [m for m in all_mistakes if SINCE <= m["date"] <= UNTIL]
   ```
   If empty → exit cleanly (nothing to report).

2. **Compose the report** (~$0.005 — one Claude Haiku call)
   ```bash
   python tools/compose_weekly_report.py \
     --since "$SINCE" --until "$UNTIL" \
     --mistakes-json .tmp/week_<since>.json \
     --streak <N> --longest-streak <N>
   # → prints path like: .tmp/report_2026-05-13.html
   ```
   Report contains: stats (days written, mistakes, streak), top 3 recurring patterns
   with examples and teaching notes, what went well, focus for next week, B2
   readiness estimate, encouragement.

3. **Send the email**
   ```bash
   python tools/send_gmail_report.py \
     --html-file .tmp/report_<since>.html \
     --subject "English Learning — Week of $SINCE"
   ```

4. **Append weekly summary to Google Doc**
   ```bash
   python tools/gdoc_append_review.py \
     --mistakes-json .tmp/week_<since>.json \
     --date "$SINCE:$UNTIL" --kind weekly
   ```

## Expected output
- An HTML email with weekly stats, top 3 patterns, focus area, B2 readiness note.
- Weekly summary appended to the Writing Journal Google Doc.

## Error handling
- **No history file**: exit cleanly (daily pipeline hasn't run yet).
- **0 mistakes this week**: exit cleanly (no data to report).
- **Claude fails**: report skipped for the week; history is intact for next run.
- **Gmail send fails**: HTML saved in `.tmp/` for manual send.
- **Google Doc append fails**: logged, email still sent.
