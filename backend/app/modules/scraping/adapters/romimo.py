"""
RomimoAdapter — sursă imobiliare Romimo.ro, județul Alba.

Categorii acoperite (confirmate live):
  - Apartamente de vânzare: /apartamente/vanzare/alba/
  - Case și vile de vânzare: /case/vanzare/alba/
  - Terenuri de vânzare:    /terenuri/vanzare/alba/

Structură HTML confirmată din probe live (2026-08-06):
  - Card:        .article-item (24/pagina)
  - Seller B2B:  .article-item-b2b-phone (companie/agenție)
  - Preț:        span.product-price → child span (număr) + span (valuta)
  - Data:        div.detail-info > div.medium-7 → "Valabil din M/D/YYYY HH:MM:SS AM"
  - Localitate:  div.detail-info > div.medium-5 → "Alba , Cugir central"
  - Seller name: div.user-profile-info
  - Imagini:     img[src*='s3.publi24.ro']
  - External ID: ultimul segment din path URL (fără .html), 32 chars hex-like
  - Paginare:    ?pag=N

Constrângeri de securitate:
  - Fără stealth, fingerprint spoofing, proxy, CAPTCHA solving.
  - Stop imediat la 403, 429 sau challenge real.
  - Delay prudent între requesturi.
  - Client HTTP reutilizat per rulare.
"""
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.config import settings
from app.modules.scraping.adapters.base import ScrapedListing, SourceAdapter

logger = logging.getLogger(__name__)

# ── Constante ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.romimo.ro"

# Categorii + URL-uri de baza (confirmate live)
CATEGORY_SEARCH_URLS: dict[str, tuple[str, str, str]] = {
    # key: (start_url, property_type, transaction_type)
    "apartamente": (
        "https://www.romimo.ro/apartamente/vanzare/alba/",
        "apartment",
        "sale",
    ),
    "case": (
        "https://www.romimo.ro/case/vanzare/alba/",
        "house",
        "sale",
    ),
    "terenuri": (
        "https://www.romimo.ro/terenuri/vanzare/alba/",
        "land",
        "sale",
    ),
}

# Subcategorie → nr. camere (din URL segment)
SUBCATEGORY_ROOMS: dict[str, int] = {
    "apartamente-1-camera": 1,
    "apartamente-2-camere": 2,
    "apartamente-3-camere": 3,
    "apartamente-4-camere": 4,
    "apartamente-5-camere": 5,
}

# Normalizare diacritice pentru localități
DIACRITICS_NORMALIZE: dict[str, str] = {
    "Sebes": "Sebeș",
    "Mures": "Mureș",
    "Campeni": "Câmpeni",
    "Teius": "Teiuș",
    "Baia de Aries": "Baia de Arieș",
    "Ocna Mures": "Ocna Mureș",
    "Aiud": "Aiud",
    "Blaj": "Blaj",
    "Cugir": "Cugir",
    "Zlatna": "Zlatna",
    "Abrud": "Abrud",
    "Campeni": "Câmpeni",
    "Alba Iulia": "Alba Iulia",
}

# Localități cu două cuvinte (pentru parsing zona)
TWO_WORD_CITIES = frozenset([
    "Alba Iulia", "Ocna Mureș", "Baia de Arieș", "Baia de Aries",
])

# Pattern external_id: 28–36 chars [0-9a-hi]
EXTERNAL_ID_RE = re.compile(r"/([0-9a-hi]{28,36})\.html$", re.I)

# Pattern preț
PRICE_RE = re.compile(r"^([\d\s]+)(EUR|lei|RON)", re.I)
PRICE_PER_M2_RE = re.compile(r"[\d\s]+EUR/m", re.I)

# Pattern dată: "Valabil din M/D/YYYY HH:MM:SS AM" sau "MM/DD/YYYY HH:MM:SS AM"
DATE_RE = re.compile(
    r"Valabil din\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)",
    re.I,
)

# ── Detector challenge ────────────────────────────────────────────────────────

def _detect_block(html: str) -> bool:
    """
    True dacă pagina este un challenge real (WAF, CAPTCHA de blocare).
    Ignoră reCAPTCHA pe pagini mari (formulare de contact = fals pozitiv).
    """
    if len(html) < 15_000:
        if re.search(r"captcha", html, re.I) and re.search(r"solve|verify you|complete", html, re.I):
            return True
    soup = BeautifulSoup(html[:4000], "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    if re.search(r"^(challenge|captcha|access denied|403)", title, re.I):
        return True
    if "cf-challenge" in html or ("Ray ID" in html and len(html) < 8000):
        return True
    return False


# ── Parsare preț ──────────────────────────────────────────────────────────────

def _parse_price(price_el: Tag | None) -> tuple[float | None, str | None, float | None, str | None]:
    """
    Extrage (price_eur, currency, original_price, original_currency) din
    elementul span.product-price.

    Structura: <span class="product-price">
                 <span>34 000</span><span>EUR</span>
                 <span class="pricePerSquare">447 EUR/m²</span>
               </span>

    Returnează (None, None, None, None) dacă nu se poate extrage.
    """
    if price_el is None:
        return None, None, None, None

    # Doar Tag-uri — NavigableString are get_text() dar nu are .get()
    children = [c for c in price_el.children if isinstance(c, Tag)]
    if not children:
        # Fallback: text brut
        raw = price_el.get_text(strip=True)
        m = PRICE_RE.match(raw)
        if m:
            val_str = re.sub(r"\s", "", m.group(1))
            try:
                val = float(val_str)
                cur = m.group(2).upper().replace("LEI", "RON")
                eur = val if cur == "EUR" else None
                return eur, cur, val, cur
            except ValueError:
                return None, None, None, None
        return None, None, None, None

    # Filtram pricePerSquare
    value_children = [c for c in children if "pricePerSquare" not in " ".join(c.get("class") or [])]

    if len(value_children) >= 2:
        num_text = value_children[0].get_text(strip=True)
        cur_text = value_children[1].get_text(strip=True).upper()
    elif len(value_children) == 1:
        # Număr și valuta împreună
        raw = value_children[0].get_text(strip=True)
        m = PRICE_RE.match(raw)
        if not m:
            return None, None, None, None
        num_text = m.group(1)
        cur_text = m.group(2).upper()
    else:
        return None, None, None, None

    val_str = re.sub(r"\s", "", num_text)
    try:
        val = float(val_str)
    except ValueError:
        return None, None, None, None

    cur = cur_text.replace("LEI", "RON")
    if cur not in ("EUR", "RON"):
        cur = "EUR"  # default Romimo

    # Conversie RON → EUR (aproximativ; orchestratorul nu o face automat)
    RON_TO_EUR = 0.2012  # curs orientativ
    if cur == "EUR":
        price_eur = val
    else:
        price_eur = round(val * RON_TO_EUR, 2)

    return price_eur, cur, val, cur


# ── Parsare dată ──────────────────────────────────────────────────────────────

def _parse_romimo_date(date_str: str) -> datetime | None:
    """
    Parsează "8/5/2026 12:31:36 PM" (format M/D/YYYY HH:MM:SS AM/PM).
    Returnează None dacă nu se poate parsa.
    """
    date_str = date_str.strip()
    try:
        return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        pass
    try:
        return datetime.strptime(date_str, "%d/%m/%Y %I:%M:%S %p")
    except ValueError:
        pass
    try:
        return datetime.strptime(date_str, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        pass
    return None


def _extract_dates(detail_info_right: Tag | None) -> tuple[datetime | None, datetime | None]:
    """
    Extrage (published_at, updated_at_source) din div.medium-7.columns.

    Text: "Valabil din 8/5/2026 12:31:36 PM Repostat automat"
    - Dacă "Repostat" e prezent → data = updated_at_source, published_at = None
    - Altfel → data = published_at
    """
    if detail_info_right is None:
        return None, None

    text = detail_info_right.get_text(" ", strip=True)
    m = DATE_RE.search(text)
    if not m:
        return None, None

    parsed = _parse_romimo_date(m.group(1))
    is_reposted = bool(re.search(r"Repostat", text, re.I))

    if is_reposted:
        return None, parsed  # published necunoscut, updated = data repost
    else:
        return parsed, None


# ── Parsare localitate ────────────────────────────────────────────────────────

def _normalize_locality(name: str) -> str:
    """Normalizează diacritice lipsă în numele localității."""
    for without, with_d in DIACRITICS_NORMALIZE.items():
        if name.strip().lower() == without.lower():
            return with_d
    return name.strip()


def _parse_location(location_el: Tag | None) -> tuple[str | None, str | None, str | None]:
    """
    Extrage (locality, zone_raw, location_raw) din div.medium-5.columns.

    Text: "Alba , Cugir central Vezi pe hartă"
    Structura: {judet} , {oras} [{zona}] ...
    Returnează (city_name, zone, location_raw).
    """
    if location_el is None:
        return None, None, None

    raw_text = location_el.get_text(" ", strip=True)
    # Taie suffix "Vezi pe hartă" și similar
    raw_text = re.sub(r"\s*[Vv]ezi pe hart[aă].*$", "", raw_text).strip()

    location_raw = raw_text  # ex: "Alba , Cugir central"

    # Split pe virgulă
    parts = [p.strip() for p in raw_text.split(",") if p.strip()]
    if len(parts) < 2:
        # Fără virgulă — încearcă să extragă direct
        return _normalize_locality(raw_text), None, location_raw

    # Prima parte = județ (ex: "Alba") → ignoram pentru city lookup
    # A doua parte = oras + zona opțional (ex: "Cugir central")
    city_zone_raw = parts[1].strip()

    # Detectare localitate cu două cuvinte
    locality = None
    zone_raw = None

    for two_word_city in TWO_WORD_CITIES:
        if city_zone_raw.lower().startswith(two_word_city.lower()):
            locality = two_word_city
            rest = city_zone_raw[len(two_word_city):].strip()
            zone_raw = rest if rest else None
            break

    if locality is None:
        # Localitate cu un cuvânt
        city_parts = city_zone_raw.split()
        if city_parts:
            locality = city_parts[0]
            zone_raw = " ".join(city_parts[1:]) if len(city_parts) > 1 else None

    if locality:
        locality = _normalize_locality(locality)

    return locality, zone_raw, location_raw


# ── Parsare seller ────────────────────────────────────────────────────────────

def _extract_seller_name(soup: BeautifulSoup) -> str | None:
    """Extrage numele vânzătorului din div.user-profile-info."""
    el = soup.select_one("div.user-profile-info, [class*='user-profile']")
    if el is None:
        return None
    # Cauta primul text relevant (ignoram "Telefon validat", "Arată telefonul" etc.)
    for child in el.find_all(["span", "strong", "a", "p", "h3", "h4"], recursive=True):
        text = child.get_text(strip=True)
        if text and len(text) >= 3 and not re.search(
            r"telefon|WhatsApp|anun[tț]|cont|[Îî]nregistr|Arată|viz[ei]", text, re.I
        ):
            return text
    # Fallback: tot textul, prima linie scurtă
    full = el.get_text(" ", strip=True)
    lines = [l.strip() for l in full.split() if l.strip() and len(l.strip()) >= 3]
    # Cautam un line care nu contine cuvinte cheie
    for line in lines[:10]:
        if not re.search(r"telefon|WhatsApp|anun[tț]|cont|Arată|validat", line, re.I):
            return line
    return None


# ── Parsare imagini ───────────────────────────────────────────────────────────

def _extract_images(soup: BeautifulSoup) -> list[str]:
    """Extrage URL-urile imaginilor (CDN s3.publi24.ro)."""
    imgs: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src"):
            src = img.get(attr, "")
            if not src:
                continue
            if re.search(r"s3\.publi24\.ro", src) and re.search(r"\.(jpg|jpeg|webp|png)", src, re.I):
                # Preferăm versiunea 'extralarge' față de 'top'
                if src not in seen:
                    seen.add(src)
                    imgs.append(src)
    # Sortăm: extralarge first, then top
    def sort_key(url: str) -> int:
        if "extralarge" in url:
            return 0
        if "large" in url:
            return 1
        return 2
    imgs.sort(key=sort_key)
    return imgs


# ── Extragere camere + suprafata + etaj din text ──────────────────────────────

def _extract_specs_from_text(text: str) -> dict[str, Any]:
    """Extrage specificații din textul paginii de detaliu."""
    specs: dict[str, Any] = {}

    m = re.search(r"(\d+)\s*cam(?:ere|era|\.)", text, re.I)
    if m:
        specs["rooms"] = int(m.group(1))

    # Suprafata utila (preferata fata de suprafata totala)
    m = re.search(r"[Ss]uprafat[aă]\s+util[aă]\s*(\d+(?:[.,]\d+)?)\s*m", text)
    if m:
        specs["usable_surface_m2"] = float(m.group(1).replace(",", "."))
        specs["surface_m2"] = specs["usable_surface_m2"]

    if "surface_m2" not in specs:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2p]", text, re.I)
        if m:
            val = float(m.group(1).replace(",", "."))
            if val > 5:  # exclude valori aberante (ex: "5 m2" pentru o poză mică)
                specs["surface_m2"] = val

    m = re.search(r"[Ee]taj\s+(parter|\d+)", text)
    if m:
        val = m.group(1)
        specs["floor"] = 0 if val.lower() == "parter" else int(val)

    m = re.search(r"[Nn]umar\s+niveluri\s*(\d+)", text)
    if m:
        specs["total_floors"] = int(m.group(1))

    m = re.search(r"[Aa]n\s+(?:constructie|construcție|edificiu)\s*[:\s]*(\d{4})", text)
    if m:
        yr = int(m.group(1))
        if 1900 <= yr <= datetime.now().year:
            specs["construction_year"] = yr

    return specs


# ── Extragere property_type din URL ──────────────────────────────────────────

def _property_type_from_url(url: str) -> tuple[str | None, str | None]:
    """
    Extrage (property_type, rooms_hint) din URL-ul de detaliu.
    Exemplu:
      .../de-vanzare/apartamente/apartamente-2-camere/... → ("apartment", 2)
      .../de-vanzare/case/case-vile/... → ("house", None)
      .../de-vanzare/terenuri/teren-intravilan/... → ("land", None)
    """
    path = urlparse(url).path.lower()
    segments = [s for s in path.split("/") if s]

    prop_type = None
    rooms_hint = None

    for seg in segments:
        if seg == "apartamente":
            prop_type = "apartment"
        elif seg in ("case", "case-vile"):
            prop_type = "house"
        elif seg == "terenuri":
            prop_type = "land"

        rooms = SUBCATEGORY_ROOMS.get(seg)
        if rooms:
            rooms_hint = rooms

    return prop_type, rooms_hint


# ── RomimoAdapter ─────────────────────────────────────────────────────────────

class RomimoAdapter(SourceAdapter):
    """
    Adaptor pentru Romimo.ro — județul Alba.
    Implementează contractul SourceAdapter fără a modifica orchestratorul.
    """

    @property
    def source_key(self) -> str:
        return "romimo"

    # ── HTTP ──────────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
        }

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers,
            follow_redirects=True,
            timeout=settings.romimo_request_timeout_seconds,
        )

    def _fetch_html(self, client: httpx.Client, url: str, retries: int = 0) -> dict | None:
        """
        Fetch HTTP cu retry pentru timeout și 5xx.
        Stop imediat la 403 sau 429.
        """
        max_retries = settings.romimo_max_retries
        for attempt in range(max_retries + 1):
            try:
                resp = client.get(url)
            except httpx.TimeoutException as exc:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("Romimo timeout %s (attempt %d) — retry in %ds", url[:80], attempt + 1, wait)
                    time.sleep(wait)
                    continue
                logger.error("Romimo timeout exhausted: %s", url[:80])
                return None
            except Exception as exc:
                logger.error("Romimo fetch error %s: %s", url[:80], exc)
                return None

            if resp.status_code in (403, 429):
                logger.warning("Romimo blocked (%d) on %s — stopping", resp.status_code, url[:80])
                return None

            if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("Romimo %d on %s — retry in %ds", resp.status_code, url[:80], wait)
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.warning("Romimo unexpected status %d on %s", resp.status_code, url[:80])
                return None

            html = resp.text
            if "<" not in html[:300]:
                logger.warning("Romimo non-HTML response on %s", url[:80])
                return None

            return {"html": html, "url": str(resp.url), "status_code": resp.status_code}

        return None

    # ── Contract SourceAdapter ────────────────────────────────────────────────

    def extract_external_id(self, url: str) -> str:
        """
        Extrage ID-ul extern din URL.
        Romimo URL: .../anunt/{slug}/{external_id}.html
        external_id = ultimul segment fără .html (32 chars hex-like).
        """
        m = EXTERNAL_ID_RE.search(url)
        if m:
            return m.group(1)
        # Fallback: ultimul segment fără extensie
        path = urlparse(url).path.rstrip("/")
        seg = path.split("/")[-1]
        return re.sub(r"\.(html?|php)$", "", seg, flags=re.I)

    def canonicalize_url(self, url: str) -> str:
        """Elimină query string și fragment; normalizează trailing slash."""
        parsed = urlparse(url)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        return clean.rstrip("/")

    def detect_block_page(self, soup: BeautifulSoup | None = None, html: str = "") -> bool:
        """True dacă pagina e un challenge WAF real (nu Google reCAPTCHA pe formular)."""
        return _detect_block(html)

    def discover_result_pages(self, max_pages: int = 100) -> list[str]:
        """
        Returnează URL-urile tuturor paginilor de rezultate pentru toate categoriile.
        Paginare: ?pag=N.
        Notă: în scrape_all() iterăm categoria pe cont propriu (cu stop pe duplicate).
        Această metodă returnează numai prima pagina per categorie (pentru progres granular).
        """
        return [url for url, _, _ in CATEGORY_SEARCH_URLS.values()]

    def discover_listing_refs(self, page_url: str) -> list[str]:
        """
        Extrage URL-urile listing-urilor dintr-o pagina de rezultate.
        Fără client persistent — pentru compatibilitate cu orchestratorul generic.
        """
        with self._make_client() as client:
            raw = self._fetch_html(client, page_url)
        if not raw:
            return []
        soup = BeautifulSoup(raw["html"], "html.parser")
        if self.detect_block_page(html=raw["html"]):
            return []
        return self._extract_listing_urls(soup)

    def _extract_listing_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extrage URL-uri unice din carduri .article-item."""
        urls: list[str] = []
        seen: set[str] = set()
        for card in soup.select(".article-item"):
            url = self._extract_card_url(card)
            if url:
                canon = self.canonicalize_url(url)
                if canon not in seen:
                    seen.add(canon)
                    urls.append(url)
        return urls

    def _extract_card_refs(self, soup: BeautifulSoup) -> list[dict]:
        """
        Extrage {url, external_id, seller_type} din carduri.
        Seller type derivat din clasa CSS a cardului (semnalul cel mai fiabil).
        """
        refs: list[dict] = []
        seen: set[str] = set()
        for card in soup.select(".article-item"):
            url = self._extract_card_url(card)
            if not url:
                continue
            ext_id = self.extract_external_id(url)
            if not ext_id or ext_id in seen:
                continue
            seen.add(ext_id)
            classes = card.get("class") or []
            seller_type = "agency" if "article-item-b2b-phone" in classes else "private"
            refs.append({
                "url": url,
                "external_id": ext_id,
                "seller_type": seller_type,
            })
        return refs

    def _extract_card_url(self, card: Tag) -> str | None:
        """Extrage URL-ul listingului dintr-un card."""
        for a in card.find_all("a", href=True):
            href = str(a["href"])
            if EXTERNAL_ID_RE.search(href):
                return href if href.startswith("http") else urljoin(BASE_URL, href)
        a = card.find("a", href=True)
        if a:
            href = str(a["href"])
            return href if href.startswith("http") else urljoin(BASE_URL, href)
        return None

    def fetch_listing(self, url: str) -> dict | None:
        """Fetch o pagină de detaliu. Returnează {html, url, status_code}."""
        with self._make_client() as client:
            return self._fetch_html(client, url)

    def parse_listing(self, raw: dict) -> ScrapedListing | None:
        """Parsează datele raw (html + url) într-un ScrapedListing."""
        return self._parse_detail_page(
            html=raw.get("html", ""),
            url=raw.get("url", ""),
            seller_type_hint=raw.get("seller_type"),
        )

    def normalize_listing(self, listing: ScrapedListing) -> ScrapedListing:
        """Post-procesare: normalizeaza localitate și calitate."""
        if listing.locality_raw:
            listing.locality_raw = _normalize_locality(listing.locality_raw)
        return listing

    # ── scrape_all — punct de intrare principal ───────────────────────────────

    def iter_batches(self, max_pages: int | None = None):
        """Livrează câte o pagină de rezultate (cu detaliile ei) — salvată imediat."""
        if max_pages is None:
            max_pages = settings.romimo_max_pages
        delay = settings.romimo_request_delay_seconds
        with self._make_client() as client:
            for cat_key, (start_url, prop_type, txn_type) in CATEGORY_SEARCH_URLS.items():
                logger.info("Romimo: starting category '%s' (max_pages=%d)", cat_key, max_pages)
                yield from self._iter_category(
                    client=client,
                    start_url=start_url,
                    category_key=cat_key,
                    prop_type=prop_type,
                    txn_type=txn_type,
                    max_pages=max_pages,
                    delay=delay,
                )

    def scrape_all(self, max_pages: int | None = None) -> list[ScrapedListing]:
        """
        Rulare completă: descoperă + fetch + parse pentru toate categoriile.
        Seller_type este transportat de la cardul de pe pagina de rezultate
        la pagina de detaliu (nu se pierde informația).
        """
        if max_pages is None:
            max_pages = settings.romimo_max_pages

        all_listings: list[ScrapedListing] = []
        delay = settings.romimo_request_delay_seconds

        with self._make_client() as client:
            for cat_key, (start_url, prop_type, txn_type) in CATEGORY_SEARCH_URLS.items():
                logger.info("Romimo: starting category '%s' (max_pages=%d)", cat_key, max_pages)
                cat_listings = self._scrape_category(
                    client=client,
                    start_url=start_url,
                    category_key=cat_key,
                    prop_type=prop_type,
                    txn_type=txn_type,
                    max_pages=max_pages,
                    delay=delay,
                )
                logger.info("Romimo: category '%s' → %d listings", cat_key, len(cat_listings))
                all_listings.extend(cat_listings)

        logger.info("Romimo: total %d listings scraped", len(all_listings))
        return all_listings

    def _scrape_category(
        self,
        client: httpx.Client,
        start_url: str,
        category_key: str,
        prop_type: str,
        txn_type: str,
        max_pages: int,
        delay: float,
    ) -> list[ScrapedListing]:
        """Iterare paginată pentru o categorie. Oprire pe duplicate sau blocare."""
        results: list[ScrapedListing] = []
        for page_results in self._iter_category(
            client=client, start_url=start_url, category_key=category_key,
            prop_type=prop_type, txn_type=txn_type, max_pages=max_pages, delay=delay,
        ):
            results.extend(page_results)
        return results

    def _iter_category(
        self,
        client: httpx.Client,
        start_url: str,
        category_key: str,
        prop_type: str,
        txn_type: str,
        max_pages: int,
        delay: float,
    ):
        """Generator: livrează anunțurile fiecărei pagini imediat ce sunt citite."""
        seen_ids: set[str] = set()
        current_url: str | None = start_url
        page_num = 0

        while current_url and page_num < max_pages:
            page_num += 1
            logger.debug("Romimo %s: page %d → %s", category_key, page_num, current_url[:80])

            raw = self._fetch_html(client, current_url)
            if not raw:
                logger.warning("Romimo %s: page %d fetch failed — stop", category_key, page_num)
                break

            if self.detect_block_page(html=raw["html"]):
                logger.warning("Romimo %s: page %d blocked — stop", category_key, page_num)
                break

            soup = BeautifulSoup(raw["html"], "html.parser")
            refs = self._extract_card_refs(soup)

            if not refs:
                logger.info("Romimo %s: page %d has 0 cards — stop", category_key, page_num)
                break

            # Deduplicare: anunturile promovate apar pe mai multe pagini
            new_refs = [r for r in refs if r["external_id"] not in seen_ids]
            if not new_refs:
                logger.info("Romimo %s: page %d all cards already seen — stop", category_key, page_num)
                break

            for ref in seen_ids.union({r["external_id"] for r in refs}):
                pass  # actualizare lazyly
            for ref in refs:
                seen_ids.add(ref["external_id"])

            # Fetch detalii
            results: list[ScrapedListing] = []
            for ref in new_refs:
                time.sleep(delay)
                detail_raw = self._fetch_html(client, ref["url"])
                if not detail_raw:
                    logger.warning("Romimo: detail fetch failed for %s", ref["url"][:80])
                    continue

                if self.detect_block_page(html=detail_raw["html"]):
                    logger.warning("Romimo: detail blocked for %s — stop category", ref["url"][:80])
                    current_url = None  # oprim categoria
                    break

                listing = self._parse_detail_page(
                    html=detail_raw["html"],
                    url=detail_raw["url"],
                    seller_type_hint=ref.get("seller_type"),
                    prop_type_override=prop_type,
                    txn_type_override=txn_type,
                )
                if listing:
                    listing = self.normalize_listing(listing)
                    results.append(listing)
                else:
                    logger.warning("Romimo: parse_listing returned None for %s", ref["url"][:80])

            if results:
                yield results

            if current_url is None:
                break

            # Pagina urmatoare
            current_url = self._find_next_page(soup, current_url)

    # ── Parsare pagina de detaliu ─────────────────────────────────────────────

    def _parse_detail_page(
        self,
        html: str,
        url: str,
        seller_type_hint: str | None = None,
        prop_type_override: str | None = None,
        txn_type_override: str | None = None,
    ) -> ScrapedListing | None:
        """
        Parsează HTML-ul paginii de detaliu Romimo.
        seller_type_hint vine de la cardul de pe pagina de rezultate.
        """
        if not html or not url:
            return None

        soup = BeautifulSoup(html, "html.parser")
        warnings: list[str] = []
        quality = "valid"

        # Titlu
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None
        if not title:
            title = url.split("/")[-1].replace(".html", "").replace("-", " ")[:100]
            warnings.append("title_fallback_from_url")

        # Description
        desc_el = soup.select_one(
            "[class*='description'], [class*='descriere'], [itemprop='description'], .desc"
        )
        description: str | None = None
        if desc_el:
            description = desc_el.get_text(" ", strip=True)[:2000]

        # Preț
        price_el = soup.select_one("span.product-price")
        price_eur, currency, original_price, original_currency = _parse_price(price_el)
        if price_eur is None:
            warnings.append("price_not_found")
            quality = "warning"

        # Data
        detail_info = soup.select_one("div.detail-info")
        right_col: Tag | None = None
        left_col: Tag | None = None
        if detail_info:
            cols = detail_info.select("div.medium-7, div[class*='medium-7']")
            if cols:
                right_col = cols[-1]
            left_cols = detail_info.select("div.medium-5, div[class*='medium-5']")
            if left_cols:
                left_col = left_cols[0]

        published_at, updated_at_source = _extract_dates(right_col)

        # Localitate + zonă
        locality, zone_raw, location_raw = _parse_location(left_col)
        if locality is None:
            warnings.append("locality_not_found")
            quality = "warning"

        # Seller
        seller_name = _extract_seller_name(soup)

        # seller_type: folosim hint din card (cel mai fiabil semnal)
        # Dacă hint nu e disponibil, cautam explicit în HTML
        if seller_type_hint in ("private", "agency", "developer"):
            seller_type = seller_type_hint
            seller_type_source = "css_class_b2b"
            seller_type_confidence = "high"
        else:
            # Fallback: detectare din text detaliu
            body_text = soup.get_text(" ", strip=True)
            if re.search(r"\bPersoan[aă]\s*fizic[aă]\b|\bPrivat\b", body_text, re.I):
                seller_type = "private"
                seller_type_source = "explicit_label"
                seller_type_confidence = "high"
            elif re.search(r"\bCompanie\b|\bFirm[aă]\b|\bAgen[tț]ie\b", body_text, re.I):
                seller_type = "agency"
                seller_type_source = "explicit_label"
                seller_type_confidence = "high"
            else:
                seller_type = "unknown"
                seller_type_source = None
                seller_type_confidence = "low"

        # Specificații din textul paginii
        page_text = soup.get_text(" ", strip=True)
        specs = _extract_specs_from_text(page_text)

        # Property type din URL (override dacă nu se determină din HTML)
        prop_type_from_url, rooms_from_url = _property_type_from_url(url)
        property_type = prop_type_override or prop_type_from_url
        transaction_type = txn_type_override or "sale"

        # Rooms: preferăm din specificații, fallback din subcategoria URL
        rooms = specs.get("rooms") or rooms_from_url

        # Imagini
        image_urls = _extract_images(soup)
        main_image_url = image_urls[0] if image_urls else None

        # raw_payload limitat (nu date personale, nu cookie-uri)
        raw_payload: dict = {}
        if original_price and original_currency:
            raw_payload["original_price"] = original_price
            raw_payload["original_currency"] = original_currency
        if location_raw:
            raw_payload["location_raw_romimo"] = location_raw

        return ScrapedListing(
            title=title,
            url=url,
            description=description,
            price_eur=price_eur,
            rooms=rooms,
            surface_m2=specs.get("surface_m2"),
            location_raw=locality,  # orchestratorul face city lookup pe acesta
            image_urls=image_urls,
            published_at=published_at,
            data_quality=quality,
            quality_warnings=warnings,
            zone_raw=zone_raw,
            zone_normalized=zone_raw.lower().strip() if zone_raw else None,
            external_id=self.extract_external_id(url),
            canonical_url=self.canonicalize_url(url),
            original_price=original_price,
            original_currency=original_currency,
            property_type=property_type,
            transaction_type=transaction_type,
            seller_type=seller_type,
            seller_name=seller_name,
            agency_name=seller_name if seller_type == "agency" else None,
            seller_type_confidence=seller_type_confidence,
            seller_type_source=seller_type_source,
            locality_raw=location_raw,
            usable_surface_m2=specs.get("usable_surface_m2"),
            floor=specs.get("floor"),
            total_floors=specs.get("total_floors"),
            construction_year=specs.get("construction_year"),
            updated_at_source=updated_at_source,
            image_count=len(image_urls),
            main_image_url=main_image_url,
        )

    # ── Paginare ──────────────────────────────────────────────────────────────

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """
        Detectează URL-ul paginii următoare.
        Romimo: paginare prin ?pag=N, link-uri cu text numeric.
        """
        # rel=next
        link_next = soup.find("link", {"rel": "next"})
        if link_next and link_next.get("href"):
            return str(link_next["href"])

        # Parseaza pagina curenta
        current_pag = 1
        m = re.search(r"[?&]pag=(\d+)", current_url)
        if m:
            current_pag = int(m.group(1))

        next_pag = current_pag + 1

        # Cauta link cu text = next_pag sau aria-label "Urmatoarea"
        nav_re = re.compile(r"^(urmatoarea|[îÎ]nainte|next|»|›)$", re.I)
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = str(a["href"])
            aria = a.get("aria-label", "")

            if nav_re.match(text) or re.search(r"urm[aă]toarea|next page", aria, re.I):
                return href if href.startswith("http") else urljoin(BASE_URL, href)

            # Link cu numarul exact al paginii urmatoare
            m_pag = re.search(r"[?&]pag=(\d+)", href)
            if m_pag and int(m_pag.group(1)) == next_pag:
                return href if href.startswith("http") else urljoin(BASE_URL, href)

        return None
