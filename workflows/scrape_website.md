# Workflow: Scrape a Single Website

## Objective
Extract clean text content from a URL and save it to `.tmp/` for further processing.

## Required Inputs
- `url` — the full URL to scrape (e.g. `https://example.com/article`)
- `output_name` _(optional)_ — custom filename for the output (no extension)

## Steps

1. **Run the scraper**
   ```
   python tools/scrape_single_site.py <url> [output_name]
   ```
2. **Verify output** — check `.tmp/<output_name>.txt` exists and contains readable content
3. **Hand off** — pass the file path to the next step in your workflow (summarization, extraction, etc.)

## Expected Output
- File at `.tmp/<output_name>.txt` containing:
  - Source URL and timestamp header
  - Cleaned body text (scripts, nav, footers removed)

## Edge Cases & Known Issues
| Situation | What to do |
|---|---|
| 403 / 429 rate limit | Wait 30s and retry once. If it persists, check if the site blocks bots. |
| Empty or garbled text | The site may be JS-rendered. Note it here and consider a Playwright-based tool. |
| Timeout | Increase `timeout` in `scrape_single_site.py` from 15s to 30s. |

## Dependencies
```
pip install requests beautifulsoup4
```
