"""
probe_imobiliare_pw.py — Playwright diagnostic probe pentru Imobiliare.ro.

Foloseste Chromium standard (fara stealth/fingerprint spoofing).
Scopuri:
  1. Verifica daca un browser real primeste HTML redat cu listing-uri.
  2. Intercepteaza requesturi XHR/fetch pentru a detecta API-uri JSON.
  3. Ruleaza acelasi diagnostic HTML ca probe_imobiliare.py.
  4. Afiseaza max 3 URL-uri de listing reale.

Rulare:
  pip install playwright
  playwright install chromium
  python3 probe_imobiliare_pw.py
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./probe.db")
os.environ.setdefault("SECRET_KEY", "probe-secret")

from bs4 import BeautifulSoup

# Re-folosim functiile de analiza din probe-ul httpx
from probe_imobiliare import (
    TMP_DIR,
    BASE_URL,
    BASE_SEARCH,
    analyse_html,
    find_listing_card_candidates,
    extract_listing_url_from_card,
    extract_external_id,
    score_element,
    PRICE_PATTERNS,
    SURFACE_PATTERNS,
    ROOMS_PATTERNS,
)

# ── Configuratie ──────────────────────────────────────────────────────────────

# Selectori CSS candidati pentru containerul de listing-uri.
# Playwright asteapta ca cel putin unul sa fie prezent inainte de a lua HTML-ul.
WAIT_SELECTORS = [
    "[class*='card']",
    "[class*='listing']",
    "[class*='result']",
    "[class*='anunt']",
    "[class*='property']",
    "article",
    "[data-id]",
    "[data-listing-id]",
    "a[href*='item-']",
]

# Pattern pentru URL-uri API JSON interesante (XHR/fetch)
API_URL_PATTERNS = [
    re.compile(r"/api/", re.I),
    re.compile(r"/graphql", re.I),
    re.compile(r"/listings?", re.I),
    re.compile(r"/anunturi", re.I),
    re.compile(r"/search", re.I),
    re.compile(r"\.json\b", re.I),
    re.compile(r"imobiliare\.ro.*/(v\d+|rest)/", re.I),
]

EXTERNAL_ID_RE = re.compile(r"item-(\d+)", re.I)


# ── Interceptare retea ────────────────────────────────────────────────────────

class NetworkCapture:
    """Colecteaza request-uri XHR/fetch relevante."""

    def __init__(self) -> None:
        self.api_requests: list[dict] = []

    def on_request(self, request) -> None:
        url = request.url
        resource_type = request.resource_type  # "xhr", "fetch", "document", etc.
        if resource_type not in ("xhr", "fetch"):
            return
        is_relevant = any(p.search(url) for p in API_URL_PATTERNS)
        entry = {
            "url": url,
            "method": request.method,
            "resource_type": resource_type,
            "is_relevant": is_relevant,
        }
        self.api_requests.append(entry)

    def relevant(self) -> list[dict]:
        return [r for r in self.api_requests if r["is_relevant"]]

    def all_xhr(self) -> list[dict]:
        return self.api_requests


# ── Probe principal ───────────────────────────────────────────────────────────

async def run_probe() -> None:
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("Playwright nu este instalat.")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    print("=== ImobiliareRo Playwright Diagnostic Probe ===")
    print(f"Target: {BASE_SEARCH}")
    print("Browser: Chromium standard (fara stealth)\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="ro-RO",
            timezone_id="Europe/Bucharest",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        # ── Interceptare request-uri ──────────────────────────────────────
        capture = NetworkCapture()
        page.on("request", capture.on_request)

        # ── Navigare ──────────────────────────────────────────────────────
        print(f"[1] Navigare catre {BASE_SEARCH} ...")
        try:
            await page.goto(BASE_SEARCH, wait_until="domcontentloaded", timeout=30_000)
        except PWTimeout:
            print("  ⚠ Timeout la navigare (30s). Continuam cu HTML partial.")
        except Exception as exc:
            print(f"  ✗ Eroare navigare: {exc}")
            await browser.close()
            return

        status = None
        # Playwright nu expune status_code direct pe page.goto in toate versiunile;
        # folosim response din goto
        try:
            response = await page.goto(BASE_SEARCH, wait_until="domcontentloaded", timeout=30_000)
            if response:
                status = response.status
        except Exception:
            pass

        if status:
            print(f"  Status HTTP: {status}")
            if status == 403:
                print("  ✗ 403 Forbidden — server blocheaza si browser-ul real.")
                print("    Imobiliare.ro foloseste protectie agresiva (Cloudflare/WAF).")
                print("    Optiuni: API JSON oficial, RSS, parteneriat date.")
                await browser.close()
                return

        # ── Asteptare continut ────────────────────────────────────────────
        print(f"[2] Asteptam continut redat (max 15s) ...")
        found_selector = None
        for sel in WAIT_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=3_000)
                found_selector = sel
                print(f"  ✓ Selector gasit: {sel}")
                break
            except PWTimeout:
                continue

        if not found_selector:
            print("  ⚠ Niciun selector asteptat gasit. Continuam cu HTML curent.")

        # Mica pauza sa se termine eventualele requesturi async
        await asyncio.sleep(2)

        # ── Extragere HTML redat ──────────────────────────────────────────
        html = await page.content()
        print(f"\n[3] HTML redat: {len(html):,} chars")

        # Salvam HTML-ul redat
        rendered_path = TMP_DIR / "imobiliare_rendered_page.html"
        rendered_path.write_text(html, encoding="utf-8")
        print(f"  HTML salvat: {rendered_path}")

        # ── Analiza structura HTML ────────────────────────────────────────
        soup = BeautifulSoup(html, "html.parser")
        print("\n[4] Diagnostic HTML (tag-uri cheie):")
        diag = analyse_html(soup, html)
        for k, v in diag["tag_counts"].items():
            print(f"  {k}: {v}")

        print(f"\n  Clase relevante ({len(diag['relevant_classes'])}):")
        for cls in diag["relevant_classes"][:20]:
            print(f"    {cls}")

        print(f"\n  href-uri cu 'item-' ({len(diag['specific_hrefs'].get('item-', []))}):")
        for h in diag["specific_hrefs"].get("item-", [])[:10]:
            print(f"    {h}")

        # ── Requesturi XHR/fetch ──────────────────────────────────────────
        all_xhr = capture.all_xhr()
        relevant_api = capture.relevant()
        print(f"\n[5] Requesturi XHR/fetch captate: {len(all_xhr)} total")
        print(f"  Relevante (API/JSON): {len(relevant_api)}")

        if relevant_api:
            print("\n  === API-uri detectate ===")
            for r in relevant_api[:15]:
                print(f"  [{r['method']}] {r['url']}")
        elif all_xhr:
            print("\n  Toate XHR/fetch (primele 15):")
            for r in all_xhr[:15]:
                print(f"  [{r['method']}] {r['url']}")
        else:
            print("  Niciun request XHR/fetch interceptat.")

        # ── Detectare carduri listing ─────────────────────────────────────
        print("\n[6] Detectare carduri listing ...")
        candidates = find_listing_card_candidates(soup)
        print(f"  Candidati cu scor >= 4: {len(candidates)}")

        # ── Extragere URL-uri reale ───────────────────────────────────────
        # Fallback suplimentar: cautam direct href-uri cu item-\d+ in pagina
        item_links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if EXTERNAL_ID_RE.search(href):
                full = href if href.startswith("http") else urljoin(BASE_URL, href)
                if full not in item_links:
                    item_links.append(full)

        print(f"\n[7] URL-uri cu 'item-\\d+' gasite direct in HTML: {len(item_links)}")
        for url in item_links[:10]:
            print(f"  {url}")

        print(f"\n[8] Primele 3 carduri detectate:")
        for i, card in enumerate(candidates[:3]):
            url = extract_listing_url_from_card(card)
            ext_id = extract_external_id(url, card) if url else None
            text = card.get_text(" ", strip=True)[:200]
            price_match = next(
                (m.group(0) for p in PRICE_PATTERNS for m in [p.search(text)] if m),
                None,
            )
            print(f"\n  [Card {i+1}] tag={card.name} cls='{' '.join(card.get('class') or [])[:60]}'")
            print(f"    URL:   {url}")
            print(f"    id:    {ext_id}")
            print(f"    pret:  {price_match}")
            print(f"    text:  {text[:150]}")

        # ── Salvam raport JSON ────────────────────────────────────────────
        report = {
            "html_length": len(html),
            "tag_counts": diag["tag_counts"],
            "relevant_classes": diag["relevant_classes"][:40],
            "item_links_count": len(item_links),
            "item_links_sample": item_links[:10],
            "xhr_total": len(all_xhr),
            "api_requests": [r["url"] for r in relevant_api[:20]],
            "all_xhr_urls": [r["url"] for r in all_xhr[:30]],
            "candidates_count": len(candidates),
        }
        report_path = TMP_DIR / "imobiliare_pw_diagnostic.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nRaport JSON salvat: {report_path}")

        await browser.close()

    print("\n=== Probe complet ===")
    print("Verificati backend/tmp/imobiliare_rendered_page.html")
    print("si backend/tmp/imobiliare_pw_diagnostic.json pentru detalii.")


if __name__ == "__main__":
    asyncio.run(run_probe())
