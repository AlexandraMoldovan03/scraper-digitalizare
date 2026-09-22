"""
OlxAdapter — OLX.ro, județul Alba, prin API-ul JSON public al site-ului
(același pe care îl folosește pagina de căutare OLX).

- region_id=28 = județul Alba
- 40 de anunțuri / cerere, max 1000 / categorie (limita OLX)
- nu deschide fiecare anunț: toate datele vin din API
- vânzătorul: câmpul `business` (true = firmă/agenție, false = persoană fizică)

OLX e sursa cu cele mai multe anunțuri de la PROPRIETARI.
"""
import logging
import re
import time
from datetime import datetime

import httpx

from app.core.config import settings
from app.modules.scraping.adapters.base import ScrapedListing, SourceAdapter

logger = logging.getLogger(__name__)

API_URL = "https://www.olx.ro/api/v1/offers/"
REGION_ALBA = 28
PAGE_SIZE = 40
MAX_OFFSET = 1000

# (property_type, transaction_type, category_id)
OLX_CATEGORIES: list[tuple[str, str, int]] = [
    ("apartment",  "sale", 907),
    ("house",      "sale", 911),
    ("land",       "sale", 709),
    ("commercial", "sale", 710),
    ("apartment",  "rent", 909),
    ("house",      "rent", 913),
    ("commercial", "rent", 710),
]

# Subcategoriile de apartamente codifică numărul de camere
ROOMS_BY_CATEGORY = {1163: 1, 1165: 2, 1167: 3, 1169: 4, 1155: 1, 1157: 2, 1159: 3, 1161: 4}
ROOMS_BY_KEY = {"one": 1, "two": 2, "three": 3, "four": 4}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ro-RO,ro;q=0.9",
    "Referer": "https://www.olx.ro/imobiliare/alba-judet/",
}


class OlxBlockedError(RuntimeError):
    """OLX refuză cererile (403/429)."""


def _num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d[\d\s.,]*", str(value))
    if not m:
        return None
    tok = re.sub(r"\s", "", m.group(0)).rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
        tok = re.sub(r"[.,]", "", tok)
    else:
        tok = tok.replace(",", ".")
    try:
        return float(tok)
    except ValueError:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def map_offer(offer: dict, property_type: str, transaction_type: str) -> ScrapedListing | None:
    """Transformă un anunț din API-ul OLX în ScrapedListing (None = ignorat)."""
    params = {p.get("key"): (p.get("value") or {}) for p in offer.get("params") or []}

    # Spațiile comerciale sunt amestecate vânzare/închiriere → parametrul „alege”
    alege = (params.get("alege") or {}).get("key")
    if alege in ("vanzare", "inchiriere"):
        if {"vanzare": "sale", "inchiriere": "rent"}[alege] != transaction_type:
            return None
    elif property_type == "land":
        title = (offer.get("title") or "").lower()
        if transaction_type == "sale" and re.search(r"inchiri|închiri|chirie", title):
            return None

    location = offer.get("location") or {}
    region = location.get("region") or {}
    if region.get("id") not in (None, REGION_ALBA):
        return None  # OLX extinde uneori căutarea în alte județe

    price_v = params.get("price") or {}
    price = _num(price_v.get("value"))
    currency = (price_v.get("currency") or "EUR").upper()
    if currency in ("LEI", "RON"):
        currency = "RON"

    surface = _num((params.get("m") or {}).get("key") or (params.get("m") or {}).get("label"))

    # Teren: unele anunțuri au prețul pe m² („55 €” pentru 510 m²)
    if property_type == "land" and price is not None and surface and price < 400 and price * surface >= 1000:
        price = round(price * surface)

    rooms = None
    if property_type in ("apartment", "house"):
        rooms = ROOMS_BY_KEY.get((params.get("rooms") or {}).get("key") or "")
        if rooms is None:
            rooms = ROOMS_BY_CATEGORY.get((offer.get("category") or {}).get("id"))
        if rooms is None:
            m = re.search(r"(\d)\s*camer", offer.get("title") or "", re.I)
            rooms = int(m.group(1)) if m else (1 if "garsonier" in (offer.get("title") or "").lower() else None)

    floor_label = (params.get("floor") or {}).get("label")
    floor = None
    if floor_label:
        if "parter" in floor_label.lower():
            floor = 0
        else:
            f = _num(floor_label)
            floor = int(f) if f is not None else None

    year = None
    constructie = (params.get("constructie") or {}).get("label") or ""
    ym = re.findall(r"(19\d{2}|20\d{2})", constructie)
    if ym:
        year = int(ym[-1])

    business = offer.get("business")
    seller_type = "agency" if business is True else "private" if business is False else "unknown"
    user = offer.get("user") or {}

    images = []
    for ph in offer.get("photos") or []:
        link = ph.get("link")
        if link:
            images.append(link.replace("{width}", "800").replace("{height}", "600"))

    city = (location.get("city") or {}).get("name")
    district = (location.get("district") or {}).get("name")

    desc = offer.get("description") or ""
    desc = re.sub(r"<br\s*/?>", "\n", desc)
    desc = re.sub(r"<[^>]+>", " ", desc).strip() or None

    warnings: list[str] = []
    if price is None:
        warnings.append("missing_price")
    if surface is None:
        warnings.append("missing_surface")
    if property_type == "apartment" and rooms is None:
        warnings.append("missing_rooms")

    return ScrapedListing(
        title=offer.get("title") or "",
        url=(offer.get("url") or "").split("?")[0],
        description=desc,
        price_eur=price if currency == "EUR" else None,
        rooms=rooms,
        surface_m2=surface,
        location_raw=city or "Alba",
        image_urls=images,
        published_at=_parse_dt(offer.get("created_time")),
        data_quality="warning" if warnings else "valid",
        quality_warnings=warnings,
        zone_raw=district,
        external_id=str(offer.get("id")),
        original_price=price,
        original_currency=currency,
        property_type=property_type,
        transaction_type=transaction_type,
        seller_type=seller_type,
        seller_name=user.get("name"),
        agency_name=(user.get("company_name") or None) if business else None,
        seller_type_source="olx_business_flag",
        seller_type_confidence="high" if business is not None else "low",
        county_raw="Alba",
        land_surface_m2=surface if property_type == "land" else None,
        floor=floor,
        construction_year=year,
        updated_at_source=_parse_dt(offer.get("last_refresh_time")),
        image_count=len(images),
        main_image_url=images[0] if images else None,
    )


class OlxAdapter(SourceAdapter):
    """Adapter OLX.ro — județul Alba, toate categoriile imobiliare."""

    @property
    def source_key(self) -> str:
        return "olx"

    def extract_external_id(self, url: str) -> str:
        m = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
        return m.group(1) if m else url.rstrip("/").split("/")[-1].replace(".html", "")

    def iter_batches(self, max_pages: int = 25):
        delay = float(getattr(settings, "olx_request_delay_seconds", 1.0))
        with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            for property_type, transaction_type, category_id in OLX_CATEGORIES:
                seen: set[str] = set()
                for page in range(max_pages):
                    offset = page * PAGE_SIZE
                    if offset >= MAX_OFFSET:
                        break
                    params = {
                        "offset": offset,
                        "limit": PAGE_SIZE,
                        "category_id": category_id,
                        "region_id": REGION_ALBA,
                        "sort_by": "created_at:desc",
                    }
                    try:
                        resp = client.get(API_URL, params=params)
                    except httpx.HTTPError as exc:
                        logger.error("OLX: eroare rețea (%s): %s", category_id, exc)
                        break
                    if resp.status_code in (403, 429):
                        raise OlxBlockedError(f"OLX a răspuns {resp.status_code}")
                    if resp.status_code >= 400:
                        logger.error("OLX: HTTP %s la categoria %s", resp.status_code, category_id)
                        break
                    data = resp.json()
                    offers = data.get("data") or []
                    batch = []
                    for offer in offers:
                        listing = map_offer(offer, property_type, transaction_type)
                        if listing and listing.external_id not in seen:
                            seen.add(listing.external_id)
                            batch.append(listing)
                    logger.info(
                        "OLX: %s/%s pagina %d — %d anunțuri", property_type, transaction_type, page + 1, len(batch)
                    )
                    if batch:
                        yield batch
                    total = min((data.get("metadata") or {}).get("total_elements") or 0, MAX_OFFSET)
                    if not offers or not (data.get("links") or {}).get("next") or offset + PAGE_SIZE >= total:
                        break
                    time.sleep(delay)

    def scrape_all(self, max_pages: int = 25) -> list[ScrapedListing]:
        results: list[ScrapedListing] = []
        for batch in self.iter_batches(max_pages=max_pages):
            results.extend(batch)
        return results
