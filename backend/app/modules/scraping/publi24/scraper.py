import json
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.modules.scraping.adapters.base import ScrapedListing


PUBLI24_ALBA_BASE_URL = (
    "https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/alba/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── JSON-LD helpers ────────────────────────────────────────────────────────────

def get_product_json_ld(soup: BeautifulSoup) -> dict | None:
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        try:
            data = json.loads(script.string or script.get_text())
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "Product":
                    return item
                for graph_item in item.get("@graph", []):
                    if isinstance(graph_item, dict) and graph_item.get("@type") == "Product":
                        return graph_item
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def extract_images_from_meta(soup: BeautifulSoup) -> list[str]:
    images: list[str] = []
    for tag in soup.find_all("meta", attrs={"property": "og:image"}):
        url = tag.get("content")
        if url and url not in images:
            images.append(url)
    return images


def parse_price_from_json_ld(product: dict | None) -> float | None:
    if not product:
        return None
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None
    raw_price = offers.get("price")
    if raw_price is None:
        return None
    try:
        return float(str(raw_price).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def parse_price_from_text(text: str) -> float | None:
    pattern = (
        r"(?<!\d)"
        r"(\d{1,3}(?:[ .]\d{3})+|\d{4,7})"
        r"\s*EUR"
        r"(?!\s*/\s*m)"
    )
    matches = re.findall(pattern, text, re.IGNORECASE)
    for raw in matches:
        normalized = raw.replace(" ", "").replace(".", "")
        try:
            value = float(normalized)
            if 5_000 <= value <= 10_000_000:
                return value
        except ValueError:
            continue
    return None


def parse_surface_m2(text: str) -> float | None:
    patterns = [
        r"Suprafata utila\s+(\d+(?:[.,]\d+)?)\s*m",
        r"Suprafață utilă\s+(\d+(?:[.,]\d+)?)\s*m",
        r"(\d+(?:[.,]\d+)?)\s*mp",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                continue
    return None


def parse_rooms(text: str) -> int | None:
    patterns = [
        r"Numar camere\s+(\d+)\s*camere",
        r"Număr camere\s+(\d+)\s*camere",
        r"(\d+)\s*camere",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def extract_images(product: dict | None) -> list[str]:
    if not product:
        return []
    images = product.get("image", [])
    if isinstance(images, str):
        return [images]
    result: list[str] = []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str):
                result.append(image)
            elif isinstance(image, dict):
                url = image.get("contentUrl") or image.get("url")
                if url:
                    result.append(url)
    return result


def extract_listing_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = urljoin("https://www.publi24.ro", tag["href"])
        is_listing = (
            "/anunturi/imobiliare/" in href
            and "/anunt/" in href
            and href.endswith(".html")
        )
        if is_listing and href not in links:
            links.append(href)
    return links


# ── Detail page ────────────────────────────────────────────────────────────────

def scrape_detail_page(url: str) -> ScrapedListing | None:
    try:
        response = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        print(f"Fetch error {url}: {exc}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    product = get_product_json_ld(soup)

    # Titlu
    if product and product.get("name"):
        title = str(product["name"])
    else:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        title = og_title.get("content", "Anunț Publi24") if og_title else "Anunț Publi24"

    # Descriere
    description = None
    if product:
        description = product.get("description")
    if not description:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc:
            description = og_desc.get("content")

    # Preț
    price_eur = parse_price_from_json_ld(product)
    if price_eur is None:
        price_eur = parse_price_from_text(page_text)

    # Suprafață și camere
    technical_text = (
        (soup.title.get_text(" ", strip=True) if soup.title else "")
        + " "
        + page_text
    )
    surface_m2 = parse_surface_m2(technical_text)
    rooms = parse_rooms(technical_text)

    # Imagini
    images = extract_images(product)
    if not images:
        images = extract_images_from_meta(soup)

    warnings: list[str] = []
    quality = "valid"

    if price_eur is None:
        warnings.append("missing_price")
        quality = "warning"
    if surface_m2 is None:
        warnings.append("missing_surface")
        quality = "warning"
    if rooms is None:
        warnings.append("missing_rooms")
        quality = "warning"

    # Localitate din og:url canonic (conține orașul în path, spre deosebire de URL-ul de fetch)
    og_url_tag = soup.find("meta", attrs={"property": "og:url"})
    og_url = og_url_tag.get("content", "") if og_url_tag else ""
    location_raw = _location_from_canonical_url(og_url) or _location_from_canonical_url(url) or "Alba"

    return ScrapedListing(
        title=title,
        url=url,
        description=description,
        price_eur=price_eur,
        rooms=rooms,
        surface_m2=surface_m2,
        location_raw=location_raw,
        image_urls=images,
        data_quality=quality,
        quality_warnings=warnings,
        property_type="apartment",
        transaction_type="sale",
    )


def _location_from_canonical_url(url: str) -> str | None:
    """
    Extrage numele localității din URL-ul canonic Publi24.
    URL-ul canonic (og:url) are structura:
      .../imobiliare/de-vanzare/.../alba/alba-iulia/anunt-XXXXX.html
    Căutăm segmentul de după 'alba' în path.
    Dacă nu găsim, returnăm None.
    """
    if not url:
        return None
    parts = url.rstrip("/").split("/")
    # Căutăm segmentul "alba" și luăm ce urmează după el
    for i, part in enumerate(parts):
        if part.lower() == "alba" and i + 1 < len(parts):
            candidate = parts[i + 1]
            # Excludem slug-uri care arată ca titluri (conțin "anunt-" sau sunt prea lungi)
            if candidate and not candidate.startswith("anunt-") and len(candidate) < 40:
                city = candidate.replace("-", " ").title()
                # Verificare minimă că nu e un slug de titlu
                if not any(w in city.lower() for w in ("apartament", "garsoniera", "vanzare", "inchiriere", "camere")):
                    return city
    return None


# ── Paginare ───────────────────────────────────────────────────────────────────

def _get_page_url(base_url: str, page: int) -> str:
    """Construiește URL-ul pentru pagina N. Publi24 folosește ?page=N."""
    if page <= 1:
        return base_url
    return f"{base_url}?page={page}"


def scrape_publi24_list_page(page_url: str) -> list[str]:
    """Returnează link-urile de anunțuri de pe o pagină de rezultate."""
    try:
        response = httpx.get(page_url, headers=HEADERS, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        print(f"List page error {page_url}: {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    return extract_listing_links(soup)


def scrape_publi24_all_pages(max_pages: int = 20) -> list[ScrapedListing]:
    """
    Punct de intrare principal pentru Publi24Adapter.
    Paginează toate anunțurile imobiliare din județul Alba.
    """
    all_links: list[str] = []
    seen_links: set[str] = set()

    for page_num in range(1, max_pages + 1):
        page_url = _get_page_url(PUBLI24_ALBA_BASE_URL, page_num)
        print(f"[publi24] Scraping page {page_num}: {page_url}")

        links = scrape_publi24_list_page(page_url)

        if not links:
            print(f"[publi24] No links on page {page_num}, stopping.")
            break

        new_links = [l for l in links if l not in seen_links]
        if not new_links:
            print(f"[publi24] No new links on page {page_num}, stopping.")
            break

        seen_links.update(new_links)
        all_links.extend(new_links)
        print(f"[publi24] Page {page_num}: {len(new_links)} new links (total: {len(all_links)})")

    print(f"[publi24] Scraping {len(all_links)} listings...")
    listings: list[ScrapedListing] = []

    for url in all_links:
        listing = scrape_detail_page(url)
        if listing:
            listings.append(listing)

    print(f"[publi24] Done: {len(listings)} listings scraped.")
    return listings


# ── Listare rapidă din paginile de rezultate (fără cereri per anunț) ─────────

PUBLI24_BASE = "https://www.publi24.ro/anunturi/imobiliare"

# (property_type, transaction_type, cale)
PUBLI24_CATEGORIES: list[tuple[str, str, str]] = [
    ("apartment",  "sale", "de-vanzare/apartamente"),
    ("house",      "sale", "de-vanzare/case"),
    ("land",       "sale", "de-vanzare/terenuri"),
    ("commercial", "sale", "de-vanzare/spatii-comerciale"),
    ("apartment",  "rent", "de-inchiriat/apartamente"),
    ("house",      "rent", "de-inchiriat/case"),
]

_RO_MONTHS = {
    "ian": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "iun": 6,
    "iul": 7, "aug": 8, "sep": 9, "oct": 10, "noi": 11, "nov": 11, "dec": 12,
}


def _fold(text: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn"
    ).lower()


def parse_number(text: str | None) -> float | None:
    """„36,000 EUR” → 36000, „42 000” → 42000, „43,66” → 43.66, „19,999 m2” → 19999."""
    if not text:
        return None
    m = re.search(r"\d{1,3}(?:[ ., ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?", text)
    if not m:
        return None
    tok = re.sub(r"[  ]", "", m.group(0))
    last = max(tok.rfind("."), tok.rfind(","))
    if last >= 0:
        after = tok[last + 1:]
        if len(after) == 3:
            tok = re.sub(r"[.,]", "", tok)
        else:
            tok = re.sub(r"[.,]", "", tok[:last]) + "." + after
    try:
        return float(tok)
    except ValueError:
        return None


def parse_ro_date(text: str | None, now: datetime | None = None) -> datetime | None:
    """„ieri 18:24”, „azi 10:05”, „11 septembrie”, „11 septembrie 2025”."""
    if not text:
        return None
    from datetime import timedelta
    now = now or datetime.utcnow()
    t = _fold(text).strip()
    hm = re.search(r"(\d{1,2}):(\d{2})", t)
    hour, minute = (int(hm.group(1)), int(hm.group(2))) if hm else (12, 0)
    if t.startswith("azi") or t.startswith("astazi"):
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t.startswith("ieri"):
        return (now - timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    m = re.search(r"(\d{1,2})\s+([a-z]{3,})\.?(?:\s+(\d{4}))?", t)
    if m and m.group(2)[:3] in _RO_MONTHS:
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            d = datetime(year, _RO_MONTHS[m.group(2)[:3]], int(m.group(1)), hour, minute)
        except ValueError:
            return None
        if not m.group(3) and d > now + timedelta(days=1):
            d = d.replace(year=year - 1)
        return d
    return None


def parse_list_page(
    html: str, property_type: str, transaction_type: str
) -> tuple[list[ScrapedListing], bool]:
    """
    Parsează cardurile de pe o pagină de rezultate Publi24.
    Returnează (anunțuri din județul Alba, există_pagina_următoare).
    Vânzătorul: cardurile firmelor au clasa `article-item-b2b-phone`.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[ScrapedListing] = []
    for card in soup.select(".article-item[data-articleid]"):
        link = card.select_one(".article-title a")
        if not link or not link.get("href"):
            continue
        url = urljoin("https://www.publi24.ro", link["href"]).split("?")[0]
        title = link.get_text(" ", strip=True)

        price_el = card.select_one(".article-price .new-price") or card.select_one(".article-price")
        price_text = price_el.get_text(" ", strip=True) if price_el else ""
        price = parse_number(price_text)
        is_ron = bool(re.search(r"lei|ron", price_text, re.I))

        info_el = card.select_one(".article-short-info")
        info = info_el.get_text(" ", strip=True) if info_el else ""
        surface = None
        for part in info.split("|"):
            if "/" in part:          # „800 EUR/m2” = preț pe m², nu suprafață
                continue
            if re.search(r"m\s*2|m²|mp", part, re.I):
                surface = parse_number(part)

        loc_el = card.select_one(".article-location span")
        loc_parts = [p.strip() for p in (loc_el.get_text(" ", strip=True) if loc_el else "").split(",") if p.strip()]
        county = loc_parts[-1] if loc_parts else None
        if county and _fold(county) != "alba":
            continue  # Publi24 amestecă uneori anunțuri din alte județe
        city = loc_parts[-2] if len(loc_parts) >= 2 else None
        city = re.sub(r"\s*\(.*?\)", "", city).strip() if city else None
        zone = ", ".join(loc_parts[:-2]) if len(loc_parts) >= 3 else None

        desc_el = card.select_one(".article-description")
        description = desc_el.get_text(" ", strip=True) if desc_el else None
        date_el = card.select_one(".article-date")
        published = parse_ro_date(date_el.get_text(" ", strip=True) if date_el else None)

        img = card.select_one(".art-img img") or card.select_one("img")
        img_src = (img.get("data-src") or img.get("src") or "") if img else ""
        images = [img_src] if img_src.startswith("http") and "placeholder" not in img_src else []

        rooms = None
        if property_type in ("apartment", "house"):
            m = re.search(r"apartamente-(\d)-camer", url)
            if m:
                rooms = int(m.group(1))
            elif "garsonier" in url or "garsonier" in _fold(title):
                rooms = 1
            else:
                rooms = parse_rooms(f"{title} {description or ''}")

        classes = card.get("class") or []
        seller_type = "agency" if "article-item-b2b-phone" in classes else "private"

        warnings: list[str] = []
        if price is None:
            warnings.append("missing_price")
        if surface is None:
            warnings.append("missing_surface")
        if property_type == "apartment" and rooms is None:
            warnings.append("missing_rooms")

        out.append(ScrapedListing(
            title=title,
            url=url,
            description=description,
            price_eur=None if is_ron else price,
            rooms=rooms,
            surface_m2=surface,
            location_raw=city or "Alba",
            image_urls=images,
            published_at=published,
            data_quality="warning" if warnings else "valid",
            quality_warnings=warnings,
            zone_raw=zone,
            external_id=url.rstrip("/").split("/")[-1].replace(".html", ""),
            original_price=price,
            original_currency="RON" if is_ron else "EUR",
            property_type=property_type,
            transaction_type=transaction_type,
            seller_type=seller_type,
            seller_type_source="css_class_b2b",
            seller_type_confidence="high",
            county_raw="Alba",
            land_surface_m2=surface if property_type == "land" else None,
        ))

    has_next = bool(re.search(r"[?&]pag=\d+", html))
    return out, has_next


def iter_publi24_batches(max_pages: int = 20, delay: float = 1.0):
    """Generator: câte o pagină de rezultate (toate categoriile, județul Alba)."""
    import time
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for property_type, transaction_type, path in PUBLI24_CATEGORIES:
            base = f"{PUBLI24_BASE}/{path}/alba/"
            seen: set[str] = set()
            for page in range(1, max_pages + 1):
                url = base if page == 1 else f"{base}?pag={page}"
                try:
                    resp = client.get(url)
                    if resp.status_code == 404:
                        break
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[publi24] eroare {url}: {exc}")
                    break
                listings, _ = parse_list_page(resp.text, property_type, transaction_type)
                has_next = f"pag={page + 1}" in resp.text
                fresh = [l for l in listings if l.url not in seen]
                seen.update(l.url for l in fresh)
                print(f"[publi24] {path} pagina {page}: {len(fresh)} anunțuri")
                if fresh:
                    yield fresh
                if not has_next or not listings:
                    break
                time.sleep(delay)


# ── Util pentru market router ──────────────────────────────────────────────────

def fetch_images_for_url(url: str) -> list[str]:
    """
    Extrage imaginile pentru un URL de anunț Publi24.
    Folosit de market router pentru a completa imagini lipsă din raw_listings.
    """
    try:
        response = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        product = get_product_json_ld(soup)
        images = extract_images(product)
        if not images:
            images = extract_images_from_meta(soup)
        return images
    except Exception as exc:
        print(f"fetch_images_for_url error {url}: {exc}")
        return []


if __name__ == "__main__":
    results = scrape_publi24_all_pages(max_pages=2)
    for item in results:
        print("\n-----")
        print("TITLE:", item.title)
        print("PRICE:", item.price_eur)
        print("ROOMS:", item.rooms)
        print("SURFACE:", item.surface_m2)
        print("LOCATION:", item.location_raw)
        print("IMAGES:", len(item.image_urls))
