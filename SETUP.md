# Setup — Step-by-Step Guide

Run `python setup.py` from the project root (with venv active). It will guide you
through each step interactively.

```bash
source .venv/bin/activate
python setup.py
```

---

## Step 1: Anthropic API Key

**What it does:** Lets Claude analyze your writing for mistakes, corrections, and explanations, and compose your daily exercise email.

**Your job:**
1. The script opens [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) in your browser
2. Click **Create Key** or copy an existing key
3. Paste it when the script asks
4. The script validates it works automatically

---

## Step 2: Notion Integration

**What it does:** Gives the system read access to your Daily Writing Practice database.

### Part A: Create the integration

1. The script opens [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **+ New Integration**
3. Fill in:
   - **Name:** `English Learning Agent`
   - **Type:** Internal
   - **Capability:** Read content only
4. Click **Create Integration**, then copy the **Internal Integration Token**
5. Paste it when the script asks for `NOTION_TOKEN`

### Part B: Share your database with the integration

1. Open your **Daily Writing Practice** database in Notion
2. Click **•••** (top right) → **Connections** → **Add connections**
3. Find **English Learning Agent** and click it

### Part C: Get your Database ID

1. Look at the URL: `https://www.notion.so/workspace/<DB_ID>?v=...`
2. Copy the 32-character segment before `?v=`
3. Paste it when the script asks for `NOTION_WRITING_DB_ID`

---

## Step 3: Google Cloud OAuth

**What it does:** Enables the system to write to Google Docs (your Writing Journal) and send emails via Gmail. One-time setup, ~5-10 minutes.

### A — Select or create a Google Cloud project

The script opens [console.cloud.google.com](https://console.cloud.google.com). Select an existing project or create one (e.g. "Personal Automations"). Press Enter when done.

### B — Configure OAuth consent screen

The script opens the OAuth consent screen. Fill in:
- **User Type:** External → Create
- **App name:** `English Learning Agent`
- **Support email + Developer contact:** your Gmail address

Click **Save and Continue** twice, then **Back to Dashboard**. Press Enter.

### C — Enable APIs (3 pages, click Enable on each)

1. **Google Drive API** — [drive.googleapis.com](https://console.cloud.google.com/apis/library/drive.googleapis.com)
2. **Google Docs API** — [docs.googleapis.com](https://console.cloud.google.com/apis/library/docs.googleapis.com)
3. **Gmail API** — [gmail.googleapis.com](https://console.cloud.google.com/apis/library/gmail.googleapis.com)

Press Enter after each one.

### D — Create OAuth credentials

1. The script opens [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials)
2. Click **+ Create Credentials** → **OAuth client ID**
3. **Application type:** Desktop app | **Name:** English Learning Agent → Create
4. Click the **Download** button, rename the file to `credentials.json`
5. Move it to the project root:
   ```bash
   mv ~/Downloads/client_secret_*.json "/Users/mahipalsingh/Development/Learning/Agentic Workflows/English Learning Agent/credentials.json"
   ```
6. Press Enter in the terminal

### E — OAuth browser "Allow"

Your browser opens with a Google permission page. Click **Allow**. The page will say "You may now close this window." `token.json` is saved automatically.

---

## Step 4: Deploy scheduler (launchd)

The script copies both plist files to `~/Library/LaunchAgents/` and loads them:

| Job | Schedule |
|-----|----------|
| `com.maahi.english-daily` | Every morning at 08:00 |
| `com.maahi.english-weekly` | Every Sunday at 19:00 |

---

## After setup completes

**Test that Notion access works:**
```bash
python tools/notion_fetch_writing.py --since 2026-05-01
```
You should see a JSON array of your recent writing entries.

**Run a manual daily ingest:**
```bash
python run_daily.py
```
You'll get an exercise email within ~1 minute if there's new writing in Notion.

---

## Cost

- **Claude (Haiku):** ~$0.002 per writing entry, ~$0.005 weekly report
- **Gmail / Drive / Docs / Notion:** Free at personal volumes

**Total:** Under $2/month.

---

## Troubleshooting

**"NOTION_TOKEN missing" error**
- Make sure you copied the Integration Token (starts with `secret_`)

**"Database not found" error**
- You created the integration but didn't share the DB with it
- Notion → Daily Writing Practice → ••• → Connections → Add connections → English Learning Agent

**"Invalid Google credentials"**
- Make sure `credentials.json` is in the project root
- If OAuth didn't complete, delete `token.json` and re-run `python setup.py`

**"The caller does not have permission" (Docs API)**
- Make sure you enabled the **Google Docs API** in Step 3C, not just the Drive API
