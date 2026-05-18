# Workflow: Save Data to Google Sheet

## Objective
Append structured rows of data to a Google Sheet tab.

## Required Inputs
- `spreadsheet_id` — found in the Google Sheets URL: `docs.google.com/spreadsheets/d/<ID>/edit`
- `sheet_name` — the tab name (default: `Sheet1`)
- `rows` — a JSON file at `.tmp/<name>.json` containing a list of row arrays

## First-Time Setup (one-time only)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → enable **Google Sheets API**
3. Create OAuth 2.0 credentials (Desktop app) → download as `credentials.json`
4. Place `credentials.json` in the project root
5. Run the tool once — a browser window opens for auth → `token.json` is saved automatically

## Steps

1. **Prepare your data** — write a `.tmp/rows.json` file in this format:
   ```json
   [
     ["Header 1", "Header 2", "Header 3"],
     ["value", "value", "value"]
   ]
   ```

2. **Run the tool**
   ```
   python tools/save_to_sheet.py <spreadsheet_id> <sheet_name> .tmp/rows.json
   ```

3. **Verify** — open the Google Sheet and confirm rows were appended

## Expected Output
- Rows appended to the specified tab
- Console: `SUCCESS: Appended N row(s) to '<sheet_name>'`

## Edge Cases & Known Issues
| Situation | What to do |
|---|---|
| `credentials.json` not found | Complete First-Time Setup above |
| `token.json` expired | Delete `token.json` and re-run to re-authenticate |
| Wrong tab name | Check exact tab name (case-sensitive) in the Sheet |

## Dependencies
```
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```
