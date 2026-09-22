"""
probe_olx.py — diagnostic live OLX Imobiliare, fără scriere în DB.

ETAPA 1: validare structură reală înainte de implementarea adaptorului.

Testează:
  - pagina de rezultate (max 1 pagina)
  - max 3 pagini de detaliu
  - JSON-LD, scripturi JSON embedded, structure HTML

Afișează:
  - status HTTP, URL final, Content-Type, dimensiune
  - titlul paginii, număr linkuri, carduri candidate
  - JSON-LD types găsite
  - scripturi JSON embedded relevante
  - external_id, seller type, date, preț, localitate
  - challenge/403/429 detection

Nu afișează:
  - cookies, token-uri, HTML complet
"""
import json
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse

sys.path.insert(0, str(Path(__file__).parent))

import httpx
from bs4 import BeautifulSoup, Tag

# ── Configurare ───────────────────────────────────────────────────────────────

BASE_URL = "https://www.olx.ro"

# Pagini de rezultate pentru județul Alba — apartamente + garsoniere
SEARCH_URLS = [
    "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-vanzare/alba/",
]

TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

REQUEST_DELAY = 1.5  # secunde între requesturi

CLIENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    # fara 'br' — evitam brotli daca nu e instalat
    "Accept-Encoding": "gzip, deflate",
}

# Patternuri pentru external_id din URL OLX
EXTERNAL_ID_PATTERNS = [
    re.compile(r"-ID([A-Za-z0-9]+)\.html", re.I),  # /d/titlu-IDxxxxxxxx.html
    re.compile(r"/([A-Za-z0-9]{10,})\.(html)?$", re.I),  # fallback slug final
]

# Pattern listing URLs OLX
LISTING_URL_RE = re.compile(r"olx\.ro/d/oferta/|olx\.ro/d/anunt/", re.I)

# ── HTTP Client ───────────────────────────────────────────────────────────────

def make_client() -> httpx.Client:
    return httpx.Client(
        headers=CLIENT_HEADERS,
        follow_redirects=True,
        timeout=30,
    )


def fetch(client: httpx.Client, url: str) -> httpx.Response | None:
    """Fetch cu detectare 403/429/challenge. Returnează None dacă blocat."""
    try:
        resp = client.get(url)
    except Exception as exc:
        print(f"  ✗ Eroare conectare: {exc}")
        return None

    print(f"  Status:        {resp.status_code}")
    print(f"  URL final:     {resp.url}")
    print(f"  Content-Type:  {resp.headers.get('content-type', '?')}")
    print(f"  Dimensiune:    {len(resp.text):,} chars")

    if resp.status_code == 403:
        print("  ⛔ 403 Forbidden — blocat de server/WAF.")
        return None
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "?")
        print(f"  ⛔ 429 Too Many Requests — Retry-After: {retry}s")
        return None
    if resp.status_code != 200:
        print(f"  ⚠ Status neașteptat: {resp.status_code}")
        return None

    # Sanity check: HTML real?
    if "<" not in resp.text[:200]:
        print("  ⚠ Răspuns nu pare HTML (posibil comprimat / binar).")
        print(f"     Content-Encoding: {resp.headers.get('content-encoding', 'none')}")
        return None

    return resp


# ── Detectare challenge ───────────────────────────────────────────────────────

def detect_challenge(soup: BeautifulSoup, html: str) -> str | None:
    """Returnează tipul de challenge dacă pagina e o pagină de blocare."""
    title = soup.title.string.strip() if soup.title else ""
    if "challenge" in title.lower() or "captcha" in title.lower():
        return f"challenge_title: {title}"
    if "cf-challenge" in html or "cf_clearance" in html:
        return "cloudflare_challenge"
    if "Ray ID" in html and "Cloudflare" in html:
        return "cloudflare_block"
    if "captcha" in html.lower() and "solve" in html.lower():
        return "captcha"
    return None


# ── JSON-LD ───────────────────────────────────────────────────────────────────

def extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    """Extrage toate nodurile JSON-LD din pagină."""
    nodes: list[dict] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = (script.string or "").strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  ⚠ JSON-LD invalid: {exc}")
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    nodes.append(item)
        elif isinstance(data, dict):
            if "@graph" in data:
                for node in data["@graph"]:
                    if isinstance(node, dict):
                        nodes.append(node)
            else:
                nodes.append(data)
    return nodes


# ── Scripturi JSON embedded ───────────────────────────────────────────────────

# ID-uri de script cunoscute pe OLX
KNOWN_SCRIPT_IDS = [
    "__olx_spa_state__",
    "__NEXT_DATA__",
    "__redux_state__",
    "state",
]

# Pattern pentru variabile JS cu date embedded
EMBEDDED_JSON_PATTERNS = [
    re.compile(r'window\.__(?:olx_spa_state|redux_state|initial_state)__\s*=\s*(\{.{50,})', re.I),
    re.compile(r'"listings":\s*\[', re.I),
    re.compile(r'"ads":\s*\[', re.I),
    re.compile(r'"items":\s*\[', re.I),
]

def extract_embedded_json(soup: BeautifulSoup) -> list[dict]:
    """Extrage scripturi JSON embedded relevante."""
    results: list[dict] = []

    # 1. Script-uri cu ID cunoscut
    for script_id in KNOWN_SCRIPT_IDS:
        tag = soup.find("script", {"id": script_id})
        if tag and tag.string:
            raw = tag.string.strip()
            try:
                data = json.loads(raw)
                results.append({"source": f"id={script_id}", "data": data, "length": len(raw)})
            except Exception:
                results.append({"source": f"id={script_id}_raw", "snippet": raw[:200], "length": len(raw)})

    # 2. Pattern-uri in scripturi anonime
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        raw = script.string or ""
        for pat in EMBEDDED_JSON_PATTERNS:
            m = pat.search(raw)
            if m:
                # Incearca sa extraga JSON din match
                snippet = raw[m.start():m.start() + 500]
                results.append({"source": f"pattern:{pat.pattern[:40]}", "snippet": snippet, "length": len(raw)})
                break

    return results


# ── External ID ───────────────────────────────────────────────────────────────

def extract_external_id(url: str, el: Tag | None = None) -> str | None:
    """
    Prioritate:
    1. -IDxxxxxxxx.html din URL
    2. data-id / data-cy din element HTML
    3. ultimul segment alfanumeric din URL
    """
    # 1. Pattern -ID<alphanum>.html
    m = re.search(r"-ID([A-Za-z0-9]+)\.html", url, re.I)
    if m:
        return m.group(1)

    # 2. data attributes
    if el is not None:
        for attr in ("data-id", "data-listing-id", "data-cy"):
            val = el.get(attr)
            if val and re.match(r"^[A-Za-z0-9]+$", str(val)):
                return str(val)

    # 3. fallback: slug final (fara extensie)
    path = urlparse(url).path.rstrip("/")
    segment = path.split("/")[-1].replace(".html", "")
    if segment and len(segment) >= 6:
        return segment

    return None


def canonicalize_url(url: str) -> str:
    """Elimină query string și fragment. Normalizează trailing slash."""
    parsed = urlparse(url)
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return clean.rstrip("/")


# ── Detectare carduri listing ─────────────────────────────────────────────────

# Selectori pentru cardurile OLX (ordinea = prioritate)
CARD_SELECTORS = [
    "[data-cy='l-card']",
    "[data-testid='l-card']",
    "li[data-aut-id='itemBox']",
    "div[data-aut-id='itemBox']",
]

def find_listing_cards(soup: BeautifulSoup) -> list[Tag]:
    """Găsește cardurile de listing din pagina de rezultate."""
    for selector in CARD_SELECTORS:
        cards = soup.select(selector)
        if cards:
            return cards

    # Fallback: orice element cu link care conține /d/oferta/
    cards = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/d/oferta/" in href or "/d/anunt/" in href:
            # Urcăm la un element parinte relevant
            parent = a.parent
            if parent and parent not in seen:
                seen.add(parent)
                cards.append(parent)
    return cards


def extract_listing_url(card: Tag) -> str | None:
    """Extrage URL-ul listing-ului dintr-un card."""
    a = card.find("a", href=True)
    if not a:
        return None
    href = a["href"]
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE_URL + href
    return urljoin(BASE_URL, href)


# ── Parsare pagina detaliu ────────────────────────────────────────────────────

MONTHS_RO = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9,
    "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}


def parse_date_ro(text: str) -> datetime | None:
    """
    Parsează formate românești:
    - Azi la HH:MM
    - Ieri la HH:MM
    - Reactualizat azi la HH:MM
    - Reactualizat la DD luna YYYY
    - DD luna YYYY
    - ISO: YYYY-MM-DDTHH:MM:SS
    """
    text = text.strip()

    # ISO
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass

    now = datetime.now()
    text_lower = text.lower()

    # "azi la HH:MM" sau "reactualizat azi la HH:MM"
    m = re.search(r"azi la (\d{1,2}):(\d{2})", text_lower)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)

    # "ieri la HH:MM"
    m = re.search(r"ieri la (\d{1,2}):(\d{2})", text_lower)
    if m:
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)

    # "DD luna YYYY" sau "reactualizat la DD luna YYYY"
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text_lower)
    if m:
        day = int(m.group(1))
        month = MONTHS_RO.get(m.group(2))
        year = int(m.group(3))
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    return None


def parse_price(text: str) -> tuple[float | None, str | None]:
    """Returnează (valoare, moneda) sau (None, None)."""
    text = text.strip()
    # EUR
    m = re.search(r"([\d\s.,]+)\s*(?:EUR|€)", text, re.I)
    if m:
        val_str = re.sub(r"[\s.]", "", m.group(1)).replace(",", ".")
        try:
            return float(val_str), "EUR"
        except ValueError:
            pass
    # LEI / RON
    m = re.search(r"([\d\s.,]+)\s*(?:lei|RON)", text, re.I)
    if m:
        val_str = re.sub(r"[\s.]", "", m.group(1)).replace(",", ".")
        try:
            return float(val_str), "RON"
        except ValueError:
            pass
    return None, None


def parse_detail_page(html: str, url: str) -> dict:
    """Parsează o pagina de detaliu OLX și returnează datele extrase."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "url": url,
        "external_id": extract_external_id(url),
        "canonical_url": canonicalize_url(url),
    }

    # Titlu
    h1 = soup.find("h1")
    result["title"] = h1.get_text(strip=True) if h1 else None

    # JSON-LD
    jsonld_nodes = extract_jsonld(soup)
    result["jsonld_types"] = [n.get("@type", "?") for n in jsonld_nodes]

    # Date din JSON-LD (Product/RealEstateListing/etc.)
    for node in jsonld_nodes:
        t = node.get("@type", "")
        if t in ("Product", "RealEstateListing", "Offer", "House", "Apartment"):
            result["jsonld_main"] = {
                "type": t,
                "name": node.get("name"),
                "description": (node.get("description") or "")[:200],
                "price": node.get("offers", {}).get("price") if isinstance(node.get("offers"), dict) else None,
                "currency": node.get("offers", {}).get("priceCurrency") if isinstance(node.get("offers"), dict) else None,
            }
            break

    # Scripturi embedded
    embedded = extract_embedded_json(soup)
    result["embedded_scripts_count"] = len(embedded)
    for emb in embedded[:2]:
        if "data" in emb:
            keys = list(emb["data"].keys())[:10] if isinstance(emb["data"], dict) else "list"
            result.setdefault("embedded_keys", []).append({"source": emb["source"], "keys": keys})

    # Preț din HTML
    price_selectors = [
        "[data-testid='ad-price-container']",
        "[data-cy='ad-price']",
        ".css-90xrc0",  # OLX price class (poate varia)
        "strong[data-testid='price']",
    ]
    for sel in price_selectors:
        el = soup.select_one(sel)
        if el:
            price_text = el.get_text(strip=True)
            price_val, price_cur = parse_price(price_text)
            result["price_raw"] = price_text
            result["price_eur"] = price_val
            result["currency"] = price_cur
            break

    # Seller type
    seller_selectors = [
        "[data-testid='seller-name']",
        "[data-cy='seller-name']",
        ".css-1wws9er",  # OLX seller class
    ]
    seller_text = None
    for sel in seller_selectors:
        el = soup.select_one(sel)
        if el:
            seller_text = el.get_text(strip=True)
            break

    # Firma vs Privat badge
    seller_type = None
    seller_type_source = None
    firma_badge = soup.find(string=re.compile(r"\bFirm[aă]\b", re.I))
    privat_badge = soup.find(string=re.compile(r"\bPrivat\b|\bPersoan[aă]\b", re.I))
    if firma_badge:
        seller_type = "agency"  # sau developer — necunoscut fara context suplimentar
        seller_type_source = "explicit_label"
    elif privat_badge:
        seller_type = "private"
        seller_type_source = "explicit_label"

    result["seller_name"] = seller_text
    result["seller_type"] = seller_type
    result["seller_type_source"] = seller_type_source

    # Data publicare / reactualizare
    date_selectors = [
        "[data-cy='ad-posted-at']",
        "[data-testid='ad-date-posted']",
        "span[data-cy='ad-postedAt']",
        "p[data-testid='location-date']",
    ]
    for sel in date_selectors:
        el = soup.select_one(sel)
        if el:
            date_text = el.get_text(strip=True)
            is_update = bool(re.search(r"reactualiz", date_text, re.I))
            parsed_dt = parse_date_ro(date_text)
            if is_update:
                result["updated_at_source_raw"] = date_text
                result["updated_at_source"] = parsed_dt.isoformat() if parsed_dt else None
            else:
                result["published_at_raw"] = date_text
                result["published_at"] = parsed_dt.isoformat() if parsed_dt else None
            break

    # Localitate / zonă din breadcrumb sau meta
    breadcrumb_nodes = jsonld_nodes
    for node in breadcrumb_nodes:
        if node.get("@type") == "BreadcrumbList":
            items = node.get("itemListElement", [])
            crumbs = [item.get("name", "") for item in items if isinstance(item, dict)]
            result["breadcrumbs"] = crumbs
            break

    # Localitate din URL sau breadcrumb
    location_from_url = urlparse(url).path.split("/")
    if len(location_from_url) >= 3:
        result["locality_from_url"] = location_from_url[-2] if location_from_url[-1].endswith(".html") else None

    # Imagini
    imgs = []
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if "olx" in src.lower() and re.search(r"\.(jpg|jpeg|webp|png)", src, re.I):
            imgs.append(src)
    result["image_count"] = len(imgs)
    result["main_image_url"] = imgs[0] if imgs else None

    return result


# ── Paginare ──────────────────────────────────────────────────────────────────

def find_next_page_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """Găsește URL-ul paginii următoare."""
    # [1] data-cy="pagination-forward"
    el = soup.find("a", {"data-cy": "pagination-forward"})
    if el and el.get("href"):
        href = el["href"]
        return href if href.startswith("http") else BASE_URL + href

    # [2] rel="next"
    el = soup.find("link", {"rel": "next"})
    if el and el.get("href"):
        return el["href"]

    # [3] <a> cu text "Înainte" / "Next" / "→"
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if re.match(r"^(Înainte|Next|›|→)$", text, re.I):
            href = a["href"]
            return href if href.startswith("http") else BASE_URL + href

    return None


# ── Probe principal ───────────────────────────────────────────────────────────

def run_probe() -> None:
    print("=" * 60)
    print("=== OLX Imobiliare — Diagnostic Probe (fără DB) ===")
    print("=" * 60)

    with make_client() as client:
        for search_url in SEARCH_URLS:
            print(f"\n{'─'*60}")
            print(f"[A] PAGINA DE REZULTATE")
            print(f"    URL: {search_url}")
            print(f"{'─'*60}")

            resp = fetch(client, search_url)
            if resp is None:
                continue

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Challenge detection
            challenge = detect_challenge(soup, html)
            if challenge:
                print(f"\n  ⛔ Challenge detectat: {challenge}")
                continue

            # Titlu
            title = soup.title.string.strip() if soup.title else "—"
            print(f"\n  Titlu pagina:  {title}")

            # Linkuri totale
            all_links = soup.find_all("a", href=True)
            print(f"  Total linkuri: {len(all_links)}")

            # JSON-LD
            jsonld_nodes = extract_jsonld(soup)
            jsonld_types = [n.get("@type", "?") for n in jsonld_nodes]
            print(f"\n  JSON-LD noduri: {len(jsonld_nodes)}")
            if jsonld_types:
                print(f"  JSON-LD tipuri: {jsonld_types}")

            # Scripturi embedded
            embedded = extract_embedded_json(soup)
            print(f"\n  Scripturi JSON embedded: {len(embedded)}")
            for emb in embedded[:3]:
                src = emb.get("source", "?")
                length = emb.get("length", 0)
                if "data" in emb and isinstance(emb["data"], dict):
                    keys = list(emb["data"].keys())[:8]
                    print(f"    [{src}] {length:,} chars — keys: {keys}")
                elif "snippet" in emb:
                    print(f"    [{src}] {length:,} chars — snippet: {emb['snippet'][:120]!r}")

            # Carduri listing
            cards = find_listing_cards(soup)
            print(f"\n  Carduri listing găsite: {len(cards)}")

            # URL-uri listing direct din HTML
            listing_urls: list[str] = []
            seen: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = str(a["href"])
                if "/d/oferta/" in href or "/d/anunt/" in href:
                    full = href if href.startswith("http") else BASE_URL + href
                    canon = canonicalize_url(full)
                    if canon not in seen:
                        seen.add(canon)
                        listing_urls.append(full)

            print(f"  URL-uri listing (/d/oferta/): {len(listing_urls)}")

            # Afișăm primele 5 URL-uri + external_id
            print(f"\n  Primele 5 URL-uri + external_id:")
            for u in listing_urls[:5]:
                eid = extract_external_id(u)
                print(f"    {eid:>15}  {u}")

            # Paginare
            next_url = find_next_page_url(soup, search_url)
            print(f"\n  Pagina urmatoare: {next_url or 'negasita'}")

            # Promovate vs organice
            promoted_count = len(soup.select("[data-cy='l-card-promoted'], [data-promoted='true'], .promoted"))
            print(f"  Carduri promovate detectate: {promoted_count}")

            # Salvam HTML result page
            result_html_path = TMP_DIR / "olx_result_page.html"
            result_html_path.write_text(html, encoding="utf-8")
            print(f"\n  HTML salvat: {result_html_path}")

            # ── Pagini de detaliu (max 3) ─────────────────────────────────
            detail_targets = listing_urls[:3]
            if not detail_targets and cards:
                # Fallback: URL-uri din carduri
                for card in cards[:3]:
                    u = extract_listing_url(card)
                    if u:
                        detail_targets.append(u)

            print(f"\n{'─'*60}")
            print(f"[B] PAGINI DE DETALIU (max 3)")
            print(f"{'─'*60}")

            if not detail_targets:
                print("\n  ⚠ Niciun URL de detaliu găsit în pagina de rezultate.")
                print("     Verificați dacă HTML-ul este redat client-side (JS).")
            else:
                for i, detail_url in enumerate(detail_targets, 1):
                    print(f"\n  [{i}] {detail_url}")
                    time.sleep(REQUEST_DELAY)

                    detail_resp = fetch(client, detail_url)
                    if detail_resp is None:
                        continue

                    detail_html = detail_resp.text
                    detail_soup = BeautifulSoup(detail_html, "html.parser")

                    challenge = detect_challenge(detail_soup, detail_html)
                    if challenge:
                        print(f"      ⛔ Challenge: {challenge}")
                        continue

                    data = parse_detail_page(detail_html, detail_url)

                    print(f"      external_id:     {data.get('external_id')}")
                    print(f"      canonical_url:   {data.get('canonical_url')}")
                    print(f"      titlu:           {data.get('title')}")
                    print(f"      pret_raw:        {data.get('price_raw')}")
                    print(f"      pret_eur:        {data.get('price_eur')}")
                    print(f"      moneda:          {data.get('currency')}")
                    print(f"      seller_name:     {data.get('seller_name')}")
                    print(f"      seller_type:     {data.get('seller_type')}")
                    print(f"      seller_type_src: {data.get('seller_type_source')}")
                    print(f"      published_at:    {data.get('published_at')}")
                    print(f"      published_raw:   {data.get('published_at_raw')}")
                    print(f"      updated_at:      {data.get('updated_at_source')}")
                    print(f"      updated_raw:     {data.get('updated_at_source_raw')}")
                    print(f"      breadcrumbs:     {data.get('breadcrumbs')}")
                    print(f"      imagini:         {data.get('image_count')}")
                    print(f"      jsonld_types:    {data.get('jsonld_types')}")
                    print(f"      embedded:        {data.get('embedded_scripts_count')} scripturi")
                    if data.get("embedded_keys"):
                        for ek in data["embedded_keys"]:
                            print(f"        [{ek['source']}] keys: {ek['keys']}")

                    # Salvam HTML detaliu
                    detail_path = TMP_DIR / f"olx_detail_{i}.html"
                    detail_path.write_text(detail_html, encoding="utf-8")
                    print(f"      HTML salvat: {detail_path}")

    print(f"\n{'='*60}")
    print("=== Probe complet ===")
    print(f"Fișiere salvate in: {TMP_DIR}")
    print()
    print("NEXT STEPS:")
    print("  1. Verificați URL-urile de listing în browser")
    print("  2. Confirmați external_id stabil")
    print("  3. Confirmați seller_type (Firmă/Privat)")
    print("  4. Confirmați structura JSON embedded (dacă există)")
    print("  5. Raportați output-ul pentru ETAPA 2")


if __name__ == "__main__":
    run_probe()
