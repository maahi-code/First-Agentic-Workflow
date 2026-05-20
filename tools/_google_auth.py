"""
Shared Google OAuth credential loader for every Google-API tool.

All Google tools (Sheets, Drive, Gmail) use the same OAuth client and token
created by setup.py. This module loads `token.json`, refreshes it if expired,
and returns a `Credentials` object ready for `googleapiclient.discovery.build`.

Why this exists: keeping the 10 lines of refresh logic in one place means
every tool gets the same behavior, and rotating credentials only touches
one file. It's not premature abstraction — every Google tool needs this.
"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

REPO_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = REPO_ROOT / "credentials.json"
TOKEN_FILE = REPO_ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_credentials():
    """Load and (if needed) refresh Google OAuth credentials.

    Raises FileNotFoundError if setup.py hasn't been run yet.
    """
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"token.json not found at {TOKEN_FILE}. Run `python setup.py` first."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())

    return creds
