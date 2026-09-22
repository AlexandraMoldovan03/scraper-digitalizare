import json
import sys

import httpx
from bs4 import BeautifulSoup


def inspect_page(url: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = httpx.get(
        url,
        headers=headers,
        timeout=30,
        follow_redirects=True,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    print("\n=== TITLE ===")
    print(soup.title.get_text(strip=True) if soup.title else None)

    print("\n=== META DESCRIPTION ===")
    meta_description = soup.find("meta", attrs={"name": "description"})
    print(
        meta_description.get("content")
        if meta_description
        else None
    )

    print("\n=== OG DATA ===")

    for tag in soup.find_all("meta"):
        prop = tag.get("property")

        if prop and prop.startswith("og:"):
            print(prop, "=", tag.get("content"))

    print("\n=== JSON-LD ===")

    scripts = soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    )

    print(f"JSON-LD blocks: {len(scripts)}")

    for index, script in enumerate(scripts, start=1):
        print(f"\n--- JSON-LD BLOCK {index} ---")

        try:
            data = json.loads(script.string or script.get_text())
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            print(script.get_text()[:3000])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.modules.scraping.publi24.inspect_page URL")
        raise SystemExit(1)

    inspect_page(sys.argv[1])
