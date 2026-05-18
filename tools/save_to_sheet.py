"""
Append rows of data to a Google Sheet.

Usage:
    python tools/save_to_sheet.py <spreadsheet_id> <sheet_name> <json_rows_file>

Arguments:
    spreadsheet_id  — The ID from the Google Sheets URL
    sheet_name      — Tab name (e.g. "Sheet1")
    json_rows_file  — Path to a JSON file containing a list of row arrays
                      e.g. [["col1", "col2"], ["val1", "val2"]]

Setup:
    1. Download credentials.json from Google Cloud Console (OAuth 2.0 → Desktop app)
    2. Place credentials.json in the project root
    3. Run once — a browser window will open for auth, then token.json is saved

Dependencies:
    pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""

import sys
import json
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_service():
    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)


def append_rows(spreadsheet_id: str, sheet_name: str, rows: list[list]) -> None:
    service = get_service()
    range_name = f"{sheet_name}!A1"
    body = {"values": rows}
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )
    updated = result.get("updates", {}).get("updatedRows", 0)
    print(f"SUCCESS: Appended {updated} row(s) to '{sheet_name}'")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    spreadsheet_id = sys.argv[1]
    sheet_name = sys.argv[2]
    rows_file = sys.argv[3]

    with open(rows_file, "r") as f:
        rows = json.load(f)

    append_rows(spreadsheet_id, sheet_name, rows)
