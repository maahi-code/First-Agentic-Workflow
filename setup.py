#!/usr/bin/env python3
"""
First-time interactive setup for the English Learning workflow.

Run once from the project root (venv active):
    python setup.py

You will be asked for:
  - Your Anthropic API key  (1 browser tab)
  - Your Notion token + DB ID  (1 browser tab + one copy from URL)
  - Your Gemini API key  (1 browser tab)
  - Google Cloud Console steps  (5-10 min, guided — one-time ever)
  - One OAuth "Allow" click in your browser

Everything else — ffmpeg, Python deps, Google Sheet creation,
Sheet headers, Drive folder, writing to .env — is handled automatically.
"""

# ── Install deps before any other imports ─────────────────────────────────────

import subprocess
import sys

_pip = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
    capture_output=True,
)
if _pip.returncode != 0:
    print(_pip.stderr.decode())
    print("ERROR: pip install failed. See above.")
    sys.exit(1)

# ── Imports (safe after pip install) ─────────────────────────────────────────

import json
import os
import webbrowser
from pathlib import Path

from dotenv import load_dotenv, set_key

# ── Constants ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent
ENV_FILE = REPO_ROOT / ".env"
CREDENTIALS_FILE = REPO_ROOT / "credentials.json"
TOKEN_FILE = REPO_ROOT / "token.json"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]

MISTAKES_HEADERS = [[
    "id", "date", "source", "source_ref", "original", "correction",
    "mistake_type", "tag", "explanation", "severity", "cefr_focus", "created_at", "naturalness_score",
]]
SUMMARIES_HEADERS = [["week_start", "total_entries", "top_3_tags", "naturalness_avg", "report_subject_line"]]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _step(n, total, title):
    print(f"\n[{n}/{total}] {title}")
    print("─" * 52)

def _ok(msg):
    print(f"  ✓  {msg}")

def _fail(msg):
    print(f"  ✗  {msg}")

def _skip(msg):
    print(f"  →  {msg} (already done)")

def _env_set(key, value):
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value

def _env_get(key):
    return os.environ.get(key, "")

def _reload_env():
    load_dotenv(ENV_FILE, override=True)

_reload_env()

# ── Step 1: ffmpeg ────────────────────────────────────────────────────────────

_step(1, 9, "Checking ffmpeg")

_found = subprocess.run(["which", "ffmpeg"], capture_output=True)
if _found.returncode == 0:
    _skip("ffmpeg already installed")
else:
    print("  ffmpeg not found — installing via Homebrew (takes ~1 min) ...")
    _install = subprocess.run(["brew", "install", "ffmpeg"])
    if _install.returncode != 0:
        _fail("brew install ffmpeg failed. Install manually: https://ffmpeg.org")
        sys.exit(1)
    _ok("ffmpeg installed")

# ── Step 2: Anthropic API key ─────────────────────────────────────────────────

_step(2, 9, "Anthropic API key  (Claude — writing/speaking analysis)")

def _validate_anthropic(key):
    try:
        import anthropic
        c = anthropic.Anthropic(api_key=key)
        c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True
    except Exception:
        return False

_ant_key = _env_get("ANTHROPIC_API_KEY")
if _ant_key and _validate_anthropic(_ant_key):
    _skip("ANTHROPIC_API_KEY valid")
else:
    print("  Opening Anthropic console ...")
    webbrowser.open("https://console.anthropic.com/settings/keys")
    print("  Create or copy an API key.")
    while True:
        _key = input("  Paste your Anthropic API key: ").strip()
        if not _key:
            continue
        print("  Validating ...", end=" ", flush=True)
        if _validate_anthropic(_key):
            _env_set("ANTHROPIC_API_KEY", _key)
            print("✓")
            _ok("Saved to .env")
            break
        print("✗")
        _fail("Key didn't work. Check it and try again.")

# ── Step 3: Notion ────────────────────────────────────────────────────────────

_step(3, 9, "Notion — Daily Writing Practice database")

def _validate_notion(token, db_id):
    try:
        from notion_client import Client
        client = Client(auth=token)
        client.databases.retrieve(database_id=db_id)
        return True, None
    except Exception as exc:
        return False, str(exc)

_notion_token = _env_get("NOTION_TOKEN")
_notion_db = _env_get("NOTION_WRITING_DB_ID")

if _notion_token and _notion_db:
    print("  Validating existing Notion credentials ...", end=" ", flush=True)
    _valid, _err = _validate_notion(_notion_token, _notion_db)
    if _valid:
        print("✓")
        _skip("Notion credentials valid")
    else:
        print("✗")
        _fail(f"Notion error: {_err}")
        _fail("Fix the token/DB ID in .env and re-run setup.")
        sys.exit(1)
else:
    if not _notion_token:
        print()
        print("  Create a Notion integration:")
        print("    1. Click '+ New integration'")
        print("    2. Name: English Learning Agent  |  Type: Internal")
        print("    3. Capability: Read content only")
        print("    4. Copy the Integration Token")
        webbrowser.open("https://www.notion.so/my-integrations")
        _notion_token = input("  Paste integration token: ").strip()
        _env_set("NOTION_TOKEN", _notion_token)

    if not _notion_db:
        print()
        print("  Share the DB with the integration:")
        print("    1. Open 'Daily Writing Practice' in Notion")
        print("    2. Click ••• → Connections → Add connections → English Learning Agent")
        print("    3. Copy the DB ID from the URL")
        print("       URL: notion.so/workspace/Title-{DB_ID}?v=...")
        print("       The DB ID is the 32-char segment before '?v='")
        _notion_db = input("  Paste DB ID: ").strip()
        _env_set("NOTION_WRITING_DB_ID", _notion_db)

    print("  Validating ...", end=" ", flush=True)
    _valid, _err = _validate_notion(_notion_token, _notion_db)
    if _valid:
        print("✓")
        _ok("Notion access confirmed")
    else:
        print("✗")
        _fail(f"Notion error: {_err}")
        _fail("Check token + DB ID. Did you share the DB with the integration?")
        sys.exit(1)

# ── Step 4: Gemini API key ────────────────────────────────────────────────────

_step(4, 9, "Gemini API key  (speaking video transcription)")

def _validate_gemini(key):
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        list(genai.list_models())
        return True
    except Exception:
        return False

_gemini_key = _env_get("GEMINI_API_KEY")
if _gemini_key and _validate_gemini(_gemini_key):
    _skip("GEMINI_API_KEY valid")
else:
    print("  Opening Google AI Studio ...")
    webbrowser.open("https://aistudio.google.com/apikey")
    print("  Create or copy an API key.")
    while True:
        _key = input("  Paste your Gemini API key: ").strip()
        if not _key:
            continue
        print("  Validating ...", end=" ", flush=True)
        if _validate_gemini(_key):
            _env_set("GEMINI_API_KEY", _key)
            print("✓")
            _ok("Saved to .env")
            break
        print("✗")
        _fail("Key didn't work. Try again.")

# ── Step 5: Google Cloud OAuth ────────────────────────────────────────────────

_step(5, 9, "Google Cloud OAuth  (Drive + Sheets + Gmail — one-time ever)")

def _load_google_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), GOOGLE_SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return creds
    return None

google_creds = _load_google_creds()

if google_creds:
    _skip("Google OAuth already configured")
else:
    if not CREDENTIALS_FILE.exists():
        print()
        print("  This takes ~5-10 minutes but you only do it once.")
        print()

        print("  A — Select or create a Google Cloud project")
        webbrowser.open("https://console.cloud.google.com/")
        input("    Press Enter when a project is selected ...")

        print()
        print("  B — Configure OAuth consent screen")
        webbrowser.open("https://console.cloud.google.com/apis/auth/consent")
        print("    1. User Type: External → Create")
        print("    2. App name: English Learning Agent")
        print("    3. User support email + Developer contact: your Gmail")
        print("    4. Save and Continue (skip Scopes) → Save and Continue → Back to Dashboard")
        input("    Press Enter when the consent screen is saved ...")

        print()
        print("  C — Enable APIs  (3 separate pages, click Enable on each)")
        webbrowser.open("https://console.cloud.google.com/apis/library/drive.googleapis.com")
        input("    Enabled Drive API? Press Enter ...")
        webbrowser.open("https://console.cloud.google.com/apis/library/sheets.googleapis.com")
        input("    Enabled Sheets API? Press Enter ...")
        webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
        input("    Enabled Gmail API? Press Enter ...")

        print()
        print("  D — Create OAuth credentials")
        webbrowser.open("https://console.cloud.google.com/apis/credentials")
        print("    1. Click '+ Create Credentials' → OAuth client ID")
        print("    2. Application type: Desktop app")
        print("    3. Name: English Learning Agent → Create")
        print("    4. Download JSON → rename it 'credentials.json'")
        print(f"    5. Move it to: {REPO_ROOT}")
        input("    Press Enter when credentials.json is in place ...")

        if not CREDENTIALS_FILE.exists():
            _fail(f"credentials.json not found at {REPO_ROOT}")
            _fail("Save it there and re-run setup.py.")
            sys.exit(1)

    print("  Running OAuth consent — your browser will open for one 'Allow' click ...")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), GOOGLE_SCOPES)
    google_creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(google_creds.to_json())
    _ok("token.json saved — Google OAuth complete")

# ── Step 6: Create Google Sheet ───────────────────────────────────────────────

_step(6, 9, "Creating Mistake Log Google Sheet")

from googleapiclient.discovery import build

_sheet_id = _env_get("GSHEET_MISTAKE_LOG_ID")
if _sheet_id:
    _skip(f"Sheet ID already set: {_sheet_id}")
else:
    print("  Creating 'English Learning — Mistake Log' ...")
    _sheets_svc = build("sheets", "v4", credentials=google_creds)
    _spreadsheet = _sheets_svc.spreadsheets().create(body={
        "properties": {"title": "English Learning — Mistake Log"},
        "sheets": [
            {"properties": {"title": "mistakes"}},
            {"properties": {"title": "summaries"}},
        ],
    }).execute()
    _sheet_id = _spreadsheet["spreadsheetId"]
    _sheet_url = f"https://docs.google.com/spreadsheets/d/{_sheet_id}"
    _env_set("GSHEET_MISTAKE_LOG_ID", _sheet_id)
    _ok(f"Sheet created → {_sheet_url}")
    webbrowser.open(_sheet_url)

# ── Step 7: Bootstrap Sheet headers ──────────────────────────────────────────

_step(7, 9, "Writing Sheet column headers")

_sheets_svc = build("sheets", "v4", credentials=google_creds)
_existing = _sheets_svc.spreadsheets().values().get(
    spreadsheetId=_sheet_id, range="mistakes!A1:A1"
).execute()

if _existing.get("values"):
    _skip("Headers already in place")
else:
    for _tab, _headers in [("mistakes", MISTAKES_HEADERS), ("summaries", SUMMARIES_HEADERS)]:
        _sheets_svc.spreadsheets().values().update(
            spreadsheetId=_sheet_id,
            range=f"{_tab}!A1",
            valueInputOption="RAW",
            body={"values": _headers},
        ).execute()
    _ok("Headers written to 'mistakes' and 'summaries' tabs")

# Apply sheet formatting + create dashboard tab
print("  Applying formatting and creating dashboard tab ...")
_fmt = subprocess.run(
    [sys.executable, "tools/sheets_format_sheet.py"],
    capture_output=True, text=True, cwd=str(REPO_ROOT),
)
if _fmt.returncode == 0:
    _ok("Sheet formatted — dashboard tab created")
else:
    print(f"  (formatting skipped: {_fmt.stderr.strip()[:80]})")

# ── Step 8: Drive folder ──────────────────────────────────────────────────────

_step(8, 9, "Google Drive — Speaking videos folder")

_folder_id = _env_get("GDRIVE_VIDEO_FOLDER_ID")
if _folder_id:
    _skip(f"GDRIVE_VIDEO_FOLDER_ID already set: {_folder_id}")
else:
    print()
    print("  Do you already have a Drive folder for speaking videos?")
    _choice = input("  y = I have one already / n = create a new one: ").strip().lower()

    if _choice == "y":
        print("  Folder URL → https://drive.google.com/drive/folders/{FOLDER_ID}")
        _folder_id = input("  Paste the folder ID: ").strip()
        _env_set("GDRIVE_VIDEO_FOLDER_ID", _folder_id)
        _ok("GDRIVE_VIDEO_FOLDER_ID saved")
    else:
        _drive_svc = build("drive", "v3", credentials=google_creds)
        _folder = _drive_svc.files().create(
            body={"name": "English Speaking Practice", "mimeType": "application/vnd.google-apps.folder"},
            fields="id,webViewLink",
        ).execute()
        _folder_id = _folder["id"]
        _env_set("GDRIVE_VIDEO_FOLDER_ID", _folder_id)
        _ok(f"Folder created → {_folder['webViewLink']}")
        webbrowser.open(_folder["webViewLink"])
        print("  Move your speaking videos into that folder when you're ready.")

# ── Step 9: Deploy launchd jobs ───────────────────────────────────────────────

_step(9, 9, "Deploying automatic scheduler (launchd)")

import shutil

_launch_agents = Path.home() / "Library" / "LaunchAgents"
_launch_agents.mkdir(parents=True, exist_ok=True)

_daily_src  = REPO_ROOT / "com.maahi.english-daily.plist"
_weekly_src = REPO_ROOT / "com.maahi.english-weekly.plist"
_daily_dst  = _launch_agents / "com.maahi.english-daily.plist"
_weekly_dst = _launch_agents / "com.maahi.english-weekly.plist"

_already_loaded = subprocess.run(
    ["launchctl", "list"], capture_output=True, text=True
).stdout

_daily_loaded  = "com.maahi.english-daily"  in _already_loaded
_weekly_loaded = "com.maahi.english-weekly" in _already_loaded

if _daily_loaded and _weekly_loaded:
    _skip("launchd jobs already loaded")
else:
    if not _daily_src.exists() or not _weekly_src.exists():
        _fail("plist files not found in project root — cannot install scheduler")
    else:
        shutil.copy2(_daily_src,  _daily_dst)
        shutil.copy2(_weekly_src, _weekly_dst)

        for _plist, _label in [
            (_daily_dst,  "com.maahi.english-daily"),
            (_weekly_dst, "com.maahi.english-weekly"),
        ]:
            _r = subprocess.run(
                ["launchctl", "load", str(_plist)],
                capture_output=True, text=True,
            )
            if _r.returncode == 0:
                _ok(f"{_label} loaded")
            else:
                _fail(f"launchctl load failed: {_r.stderr.strip()[:80]}")

        print()
        print("  Schedule:")
        print("    Daily  →  every morning at 08:00")
        print("    Weekly →  every Sunday at 19:00")

# ── Done ──────────────────────────────────────────────────────────────────────

print()
print("=" * 52)
print("  Setup complete! The system runs itself from here.")
print()
print("  Test now (optional):")
print("    python run_daily.py")
print()
print("  You will get an exercise email at ms4341547@gmail.com")
print("  within ~1 minute if there is new writing in Notion.")
print("=" * 52)
