import json
import re
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
