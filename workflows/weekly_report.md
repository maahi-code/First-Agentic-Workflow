# Workflow: Weekly Progress Report

## Objective
Summarize the week's mistakes, compose an HTML report with Claude, and email it
to Maahi. This closes the feedback loop — patterns become visible, not invisible.

## When to run
Every Sunday evening (automated via launchd after M8 setup).

## Prerequisites
- `GSHEET_MISTAKE_LOG_ID`, `ANTHROPIC_API_KEY`, `REPORT_TO_EMAIL` in `.env`
- At least one week of ingested data in the Sheet

## Tools used (in order)
1. `tools/sheets_query_mistakes.py` — fetch this week's mistakes from Sheet
2. `tools/compose_weekly_report.py` — Claude summarizes + renders HTML
3. `tools/send_gmail_report.py`     — sends the email via Gmail API

## Steps

1. **Query this week's mistakes**
   ```bash
   SINCE=$(date -v-7d +%F)   # 7 days ago on macOS
   UNTIL=$(date +%F)
   python tools/sheets_query_mistakes.py --since "$SINCE" --until "$UNTIL" \
     > .tmp/week_mistakes.json
   ```

2. **Compose the report** (one Claude Haiku call — ~$0.005)
   ```bash
   python tools/compose_weekly_report.py \
     --since "$SINCE" --until "$UNTIL" \
     --mistakes-json .tmp/week_mistakes.json
   # → prints path like: .tmp/report_2026-05-13.html
   ```

3. **Send the email**
   ```bash
   python tools/send_gmail_report.py \
     --html-file .tmp/report_2026-05-13.html \
     --subject "English Learning — Week of $SINCE"
   ```

## Expected output
- An HTML email in Maahi's inbox with:
  - Stats (entries analyzed, total mistakes, avg per entry)
  - Top 3 recurring patterns with examples and teaching notes
  - What went well this week
  - One focused exercise for next week
  - A short encouraging note

## Error handling
- **0 mistakes for the week**: send a gentle nudge email instead of skipping silently.
  Update the compose step to detect an empty array and send a "you didn't journal
  this week" note (add this to compose_weekly_report.py when needed).
- **Claude fails**: retry once. If still failing, the week's report is skipped
  (the Sheet still has all the data — the analysis just isn't emailed).
- **Gmail send fails**: retry once. If still failing, the HTML is saved in .tmp/
  so it can be sent manually.
