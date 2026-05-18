"""
Scrape a single URL and save the cleaned text content to .tmp/.

Usage:
    python tools/scrape_single_site.py <url> [output_filename]

Output:
    .tmp/<output_filename>.txt  (defaults to domain name + timestamp)
"""

import sys
import os
import re
from datetime import datetime
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install requests beautifulsoup4")
    sys.exit(1)

OUTPUT_DIR = ".tmp"


def scrape(url: str, output_name: str | None = None) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WAT-scraper/1.0)"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not output_name:
        domain = urlparse(url).netloc.replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"{domain}_{timestamp}"

    output_path = os.path.join(OUTPUT_DIR, f"{output_name}.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"URL: {url}\n")
        f.write(f"Scraped: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    print(f"SUCCESS: Saved to {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    output_name = sys.argv[2] if len(sys.argv) > 2 else None
    scrape(url, output_name)
