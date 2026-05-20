# Setup — Detailed Step-by-Step Guide

Run `python setup.py` from the project root (with venv active). It will guide you through each step interactively. This document explains what each step does and how to complete it.

```bash
source .venv/bin/activate
python setup.py
```

---

## Step 1: ffmpeg

**What it does:** Extracts audio from your speaking videos so Gemini can transcribe them cheaply.

**What happens:** The script checks if ffmpeg is installed. If not, it runs `brew install ffmpeg` automatically.

**Your job:** Just let it run. Takes ~1 min.

---

## Step 2: Anthropic API Key

**What it does:** Lets Claude analyze your writing and speaking for mistakes, corrections, and explanations.

**Your job:**
1. The script opens [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) in your browser
2. Click **Create Key** or copy an existing key
3. Paste it when the script asks
4. The script validates it works

---

## Step 3: Notion Integration

### Part A: Create the integration

**What it does:** Gives the system permission to read your Daily Writing Practice database.

**Your job:**
1. The script opens [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **+ New Integration**
3. Fill in:
   - **Name:** `English Learning Agent`
   - **Associated workspace:** Select your personal workspace
   - **Type:** Internal (not Public)
4. Click **Create Integration**
5. You'll see the "Internal Integration Token" — click **Show** then **Copy**
6. Paste it when the script asks for `NOTION_TOKEN`

### Part B: Share your Daily Writing Practice database with the integration

**What it does:** Without this, the integration can't access your DB even with the token.

**Your job:**
1. Open Notion and go to your **Daily Writing Practice** database
2. Click the **•••** menu (top right of the page)
3. Click **Connections**
4. Click **Add connections**
5. Find and click **English Learning Agent** (the integration you just created)
6. You'll see a green checkmark — the DB is now shared with the integration

### Part C: Get your Database ID

**What it does:** Tells the system which database to read from.

**Your job:**
1. Still in your **Daily Writing Practice** database, look at the URL in your browser
   - It looks like: `https://www.notion.so/workspace-name/<DB_ID>?v=...`
2. Copy the 32-character segment between the last `/` and `?v=`
   - Example: If the URL is `https://www.notion.so/workspace/MyDatabase-abc123def456ghi789?v=...`
   - The DB ID is `abc123def456ghi789`
3. Paste it when the script asks for `NOTION_WRITING_DB_ID`

### Important: Database structure

The script will read your writing using one of two modes:

**Mode 1: Page body (default)** — The writing is in the page itself (paragraphs, headings, bullets). This is the most common setup.

**Mode 2: Rich-text property** — The writing is stored in a database column (e.g., a property called "Entry").

The script defaults to Mode 1. If your setup is different, you'll need to run:
```bash
python tools/notion_fetch_writing.py --since 2026-05-13 --mode property --property "PropertyName"
```

---

## Step 4: Gemini API Key

**What it does:** Transcribes your speaking videos so the system can analyze your spoken English.

**Your job:**
1. The script opens [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API Key**
3. Choose **Create API key in new Google Cloud project**
4. A key will appear — click **Copy**
5. Paste it when the script asks for `GEMINI_API_KEY`

---

## Step 5: Google Cloud OAuth Setup

**What it does:** Enables the system to access your Google Drive (videos), Google Sheets (mistake log), and Gmail (weekly reports) — all from one OAuth login.

**This is the longest step (~5-10 minutes), but only done once.**

### Step 5A: Select or create a Google Cloud project

**Your job:**
1. The script opens [console.cloud.google.com](https://console.cloud.google.com)
2. Look at the top of the page — you'll see a dropdown that says "Select a project"
3. Either:
   - Pick an existing project if you have one (e.g., "Personal Automations")
   - OR click **New Project**, name it "Personal Automations" or "English Learning", and click **Create**
4. Once a project is selected, press Enter in the terminal

### Step 5B: Configure OAuth consent screen

**Your job:**
1. The script opens the OAuth consent screen page in Google Cloud Console
2. You'll see a form. Fill it out:
   - **User Type:** Select **External** → click **Create**
   - **App name:** `English Learning Agent`
   - **User support email:** `ms4341547@gmail.com`
   - **Developer contact information:** `ms4341547@gmail.com`
3. Click **Save and Continue**
4. You'll see a "Scopes" page — click **Save and Continue** again (no scopes needed here)
5. You'll see a "Summary" page — click **Back to Dashboard**
6. Press Enter in the terminal

### Step 5C: Enable the three APIs

The script will open each of these three pages. On each one, click the **Enable** button:

1. **Google Drive API** — https://console.cloud.google.com/apis/library/drive.googleapis.com
   - Click **Enable** → wait for it to turn blue
   - Press Enter in the terminal

2. **Google Sheets API** — https://console.cloud.google.com/apis/library/sheets.googleapis.com
   - Click **Enable**
   - Press Enter in the terminal

3. **Gmail API** — https://console.cloud.google.com/apis/library/gmail.googleapis.com
   - Click **Enable**
   - Press Enter in the terminal

### Step 5D: Create OAuth credentials (the part you'll download)

**Your job:**
1. The script opens https://console.cloud.google.com/apis/credentials
2. Click **+ Create Credentials** at the top
3. Select **OAuth client ID**
4. You'll see "User Type: External" — click **Create consent screen**
   - Fill in the same info as Step 5B, save, come back
5. Back at the OAuth client ID page:
   - **Application type:** Select **Desktop app**
   - **Name:** `English Learning Agent`
   - Click **Create**
6. A popup appears with your credentials — click the **Download** button (it downloads a JSON file)
7. You'll see a file named something like `client_secret_<...>.json` in your Downloads
8. **Move it to the project root and rename it to `credentials.json`**
   ```bash
   mv ~/Downloads/client_secret_*.json "/Users/mahipalsingh/Development/Learning/Agentic Workflows/First Agentic Workflow/credentials.json"
   ```
9. Press Enter in the terminal

### Step 5E: OAuth browser "Allow" (automatic)

**Your job:** Just click "Allow" when your browser opens.

Once you've moved `credentials.json` and pressed Enter:
- Your browser will open asking for permission
- Click **Allow** (or the equivalent button)
- The page will say "You may now close this window"
- Close it
- The script saves `token.json` automatically

---

## Step 6: Create Google Sheet

**What it does:** Creates the "Mistake Log" where all corrections are stored — visible, sortable, queryable.

**Your job:** The script creates this automatically. You'll see a link in the browser. You can close it or leave it open.

---

## Step 7: Bootstrap Sheet headers

**What it does:** Writes the column headers so the mistake log has structure.

**Your job:** None — automatic.

---

## Step 8: Google Drive folder

**What it does:** Creates a folder for your speaking practice videos.

**Your job:**
- If you already have a folder: The script asks for the folder ID (from the URL)
- If you don't have one yet: The script creates a new folder called "English Speaking Practice" and opens it. You can move videos into it later.

---

## After setup completes

You'll see:

```
==================================================
  Setup complete!

  Verify M1 (once NOTION_TOKEN is set):
    python tools/notion_fetch_writing.py --since 2026-05-13

  Then start your first daily ingest:
    Tell Claude: 'run daily ingest'
==================================================
```

**Test that Notion access works:**
```bash
python tools/notion_fetch_writing.py --since 2026-05-13
```

You should see a JSON array of your recent writing entries. If it errors, check:
- Did you share the DB with the integration? (most common mistake)
- Is the token correct?
- Is the DB ID correct?

---

## Cost

- **Claude (Haiku)**: ~$0.002 per writing entry. Daily.
- **Gemini**: ~$0.01 per speaking video (ffmpeg compression cuts payload ~10×).
- **Gmail / Drive / Sheets / Notion**: Free at personal volumes.

**Total:** Under $5/month.

---

## Troubleshooting

**"NOTION_TOKEN missing" error**
- Make sure you copied the Integration Token (not the Integration ID)
- The token starts with `secret_`

**"Database not found" error**
- You created the integration but didn't share the DB with it
- Go back to Notion → Daily Writing Practice → ••• → Connections → Add connections → English Learning Agent

**"Invalid Google credentials"**
- Make sure `credentials.json` is in the project root (exact path: `/Users/mahipalsingh/Development/Learning/Agentic Workflows/First Agentic Workflow/credentials.json`)
- If the OAuth flow didn't complete, delete `token.json` and re-run `python setup.py`

**ffmpeg install fails**
- You might not have Homebrew. Install from https://brew.sh then re-run setup.py

---

## Next: First data ingest

Once setup completes, the system is ready. I'll build M2 (Claude analysis tool) and we'll process your first day of writing.
