"""
ImobiliareRoAdapter — HTTP standard (httpx) + JSON-LD parsing.

Metoda de acces: httpx standard, fără Playwright/stealth/proxy/CAPTCHA.
Imobiliare.ro: HTML server-rendered cu date în <script type="application/ld+json">.
NU mai folosi __NEXT_DATA__ (site migrat de la Next.js).

Guard de activare:
  SCRAPE_IMOBILIARE_RO_ENABLED=true AND SCRAPE_IMOBILIARE_RO_AUTHORIZED=true

Blocare: Dacă primim 403/429/challenge → ImobiliareRoBlockedError.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.modules.scraping.adapters.base import ScrapedListing, SourceAdapter

logger = logging.getLogger(__name__)

# ── Excepții proprii ──────────────────────────────────────────────────────────

class ImobiliareRoNotAuthorizedError(RuntimeError):
    """Adaptor dezactivat sau neautorizat prin config."""

class ImobiliareRoBlockedError(RuntimeError):
    """Serverul blochează accesul (403/429/challenge)."""

# ── Constante ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.imobiliare.ro"

ALBA_CATEGORIES = [
    ("apartment", "sale", "vanzare-apartamente/judet-alba"),
    ("house",     "sale", "vanzare-case-si-vile/judet-alba"),
    ("land",      "sale", "vanzare-terenuri/judet-alba"),
    ("commercial","sale", "vanzare-spatii-comerciale/judet-alba"),
]

# Structura actuală a site-ului (2026): /{vanzare|inchiriere}-{categorie}/judetul-alba?page=N
# Pagina de rezultate conține toate anunțurile în JSON (<div id="app" data-page="...">),
# deci nu mai e nevoie de câte o cerere pentru fiecare anunț.
INERTIA_CATEGORIES = [
    ("apartment",  "sale", "vanzare-apartamente/judetul-alba"),
    ("house",      "sale", "vanzare-case-vile/judetul-alba"),
    ("land",       "sale", "vanzare-terenuri/judetul-alba"),
    ("commercial", "sale", "vanzare-spatii-comerciale/judetul-alba"),
    ("apartment",  "rent", "inchiriere-apartamente/judetul-alba"),
    ("house",      "rent", "inchiriere-case-vile/judetul-alba"),
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}

_BLOCK_INDICATORS = [
    "cf-browser-verification",
    "checking your browser",
    "captcha",
    "ddos-guard",
    "access denied",
    "enable javascript",
    "just a moment",
    "ray id",
]

# Tipuri JSON-LD care nu sunt listing-uri imobiliare
_NON_LISTING_TYPES = frozenset({
    "Person", "Organization", "BreadcrumbList", "WebSite", "WebPage",
    "SearchAction", "ItemList", "CollectionPage", "SearchResultsPage",
    "WebPageElement", "SiteNavigationElement", "WPHeader", "WPFooter",
    "PostalAddress", "ImageObject", "Offer", "PriceSpecification",
})

# ── JSON-LD helpers (module-level, refolosibil din probe) ─────────────────────

def iter_jsonld_nodes(soup: BeautifulSoup) -> Iterable[dict]:
    """
    Găsește toate scripturile application/ld+json, parsează JSON valid,
    acceptă dict simplu, listă sau @graph.
    Ignoră blocurile invalide și raportează warning.
    """
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = (script.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("JSON-LD bloc invalid, ignorat: %s", exc)
            continue

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
        elif isinstance(data, dict):
            if "@graph" in data:
                for node in data["@graph"]:
                    if isinstance(node, dict):
                        yield node
            else:
                yield data


def is_listing_node(node: dict) -> bool:
    """
    Detectează dacă un nod JSON-LD este un listing imobiliar.
    Nu se bazează exclusiv pe @type — folosește combinație de semnale.
    """
    if not isinstance(node, dict):
        return False

    node_type = node.get("@type", "")
    if isinstance(node_type, list):
        type_str = " ".join(str(t) for t in node_type)
    else:
        type_str = str(node_type)

    # Excludem explicit tipurile ne-listing
    for non_type in _NON_LISTING_TYPES:
        if non_type.lower() in type_str.lower():
            return False

    # Semnal puternic: @id conține /schema/Product/item-
    node_id = node.get("@id", "")
    if re.search(r"/schema/Product/item-\d+", node_id):
        return True

    # Semnale multiple slabe
    score = 0
    offers = node.get("offers") or {}
    if isinstance(offers, dict):
        price_spec = offers.get("priceSpecification") or {}
        if isinstance(price_spec, dict) and price_spec.get("price") is not None:
            score += 2
        elif offers.get("price") is not None:
            score += 2

    if node.get("description"):
        score += 1
    if node.get("name") or node.get("headline"):
        score += 1
    if node.get("address"):
        score += 1
    if node.get("image"):
        score += 1
    if node.get("url") and "imobiliare.ro" in str(node.get("url", "")):
        score += 1

    return score >= 3


# ── ImobiliareRoAdapter ───────────────────────────────────────────────────────

class ImobiliareRoAdapter(SourceAdapter):
    """Adapter pentru imobiliare.ro — județul Alba, via JSON-LD."""

    @property
    def source_key(self) -> str:
        return "imobiliare_ro"

    # ── Block detection ───────────────────────────────────────────────────────

    def detect_block_page(self, html: str, status_code: int = 200) -> bool:
        if status_code in (403, 429):
            return True
        if len(html) < 500 and "</html>" not in html.lower():
            return True
        html_lower = html.lower()
        return any(indicator in html_lower for indicator in _BLOCK_INDICATORS)

    # ── HTTP client ───────────────────────────────────────────────────────────

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            headers=HEADERS,
            timeout=settings.scrape_imobiliare_ro_request_timeout_seconds,
            follow_redirects=True,
        )

    def _fetch_with_retry(self, client: httpx.Client, url: str) -> tuple[str, int]:
        """Fetch cu retry pe timeout și 5xx. Fără retry pe 403/404/429/challenge."""
        delay = settings.scrape_imobiliare_ro_request_delay_seconds
        max_retries = settings.scrape_imobiliare_ro_max_retries
        last_exc = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                backoff = delay * (2 ** (attempt - 1))
                logger.info("Retry %d/%d pentru %s (backoff %.1fs)", attempt, max_retries, url[:80], backoff)
                time.sleep(backoff)
            else:
                time.sleep(delay)

            try:
                resp = client.get(url)
                status = resp.status_code
                html = resp.text

                if status in (403, 429) or self.detect_block_page(html, status):
                    raise ImobiliareRoBlockedError(f"Blocat la {url[:80]} — status={status}")

                if status == 404:
                    return html, status

                if status >= 500:
                    logger.warning("5xx la %s (status=%d) — retry", url[:80], status)
                    last_exc = RuntimeError(f"HTTP {status}")
                    continue

                return html, status

            except ImobiliareRoBlockedError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Timeout/connect error la %s: %s — retry", url[:80], exc)
                last_exc = exc
                continue
            except httpx.HTTPError as exc:
                logger.warning("HTTP error la %s: %s", url[:80], exc)
                raise

        raise RuntimeError(f"Toate retrăile epuizate pentru {url[:80]}: {last_exc}")

    # ── URL helpers ───────────────────────────────────────────────────────────

    def extract_external_id(self, url: str) -> str | None:
        """
        Extrage ID-ul extern din URL.
        Prioritate: item-{id} numeric, apoi alfanumeric la final de segment.
        """
        if not url:
            return None
        clean = url.split("?")[0].split("#")[0].rstrip("/")

        # Pattern item-{digits} (format actual al site-ului)
        match = re.search(r"item-(\d+)", clean)
        if match:
            return match.group(1)

        # Fallback: alfanumeric la finalul ultimului segment
        last_segment = clean.split("/")[-1]
        match = re.search(r"([A-Z0-9]{6,})$", last_segment)
        if match:
            return match.group(1)

        return None

    def canonicalize_url(self, url: str) -> str:
        """Formă canonică: fără query, fără fragment, lowercase, fără trailing slash."""
        parsed = urlparse(url)
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "", "", ""
        ))

    # ── External ID din nod JSON-LD ───────────────────────────────────────────

    def _extract_external_id_from_node(self, node: dict) -> str | None:
        """
        Extrage external_id dintr-un nod JSON-LD.
        Ordinea: @id → sku/productID/identifier → url field.
        """
        # 1. Din @id: https://www.imobiliare.ro/#/schema/Product/item-275791517
        node_id = node.get("@id", "")
        match = re.search(r"/item-(\d+)", node_id)
        if match:
            return match.group(1)

        # 2. Din sku/productID/identifier
        for key in ("sku", "productID", "identifier"):
            val = node.get(key)
            if val and isinstance(val, (str, int)):
                val_str = str(val).strip()
                if val_str.isdigit() or re.match(r"^[A-Z0-9]{4,}$", val_str):
                    return val_str

        # 3. Din câmpul url al nodului
        url = node.get("url")
        if url and isinstance(url, str):
            return self.extract_external_id(url)

        return None

    # ── URL real al listing-ului ──────────────────────────────────────────────

    def extract_listing_url(
        self,
        node: dict,
        soup: BeautifulSoup | None = None,
        external_id: str | None = None,
    ) -> str | None:
        """
        Determină URL-ul real navigabil al unui listing din JSON-LD + HTML.
        @id de forma /#/schema/Product/item-X nu este navigabil.
        """
        # 1. node.url direct (navigabil)
        url = node.get("url")
        if url and isinstance(url, str) and "imobiliare.ro" in url and "#" not in url:
            return self.canonicalize_url(url)

        # 2. offers.url
        offers = node.get("offers") or {}
        if isinstance(offers, dict):
            url = offers.get("url")
            if url and isinstance(url, str) and "imobiliare.ro" in url and "#" not in url:
                return self.canonicalize_url(url)

        # 3. mainEntityOfPage
        mep = node.get("mainEntityOfPage")
        if isinstance(mep, str) and "imobiliare.ro" in mep and "#" not in mep:
            return self.canonicalize_url(mep)
        if isinstance(mep, dict):
            mep_url = mep.get("@id") or mep.get("url")
            if mep_url and "imobiliare.ro" in mep_url and "#" not in mep_url:
                return self.canonicalize_url(mep_url)

        # 4. itemListElement
        ile = node.get("itemListElement")
        if isinstance(ile, list):
            for elem in ile:
                if isinstance(elem, dict):
                    u = elem.get("url") or elem.get("@id")
                    if u and isinstance(u, str) and "imobiliare.ro" in u and "#" not in u:
                        return self.canonicalize_url(u)

        # 5. Caută în HTML link-ul care conține item-{external_id}
        if external_id and soup:
            pattern = f"item-{external_id}"
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if pattern in href:
                    if href.startswith("/"):
                        href = BASE_URL + href
                    if "imobiliare.ro" in href and "#" not in href:
                        return self.canonicalize_url(href)

        return None

    # ── Paginare ──────────────────────────────────────────────────────────────

    def discover_result_pages(self, category_path: str, max_pages: int = 20) -> list[str]:
        """Construiește URL-urile paginilor de rezultate."""
        base = f"{BASE_URL}/{category_path}"
        pages = [base]
        for i in range(2, max_pages + 1):
            pages.append(f"{base}?pagina={i}")
        return pages

    def extract_next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """
        Extrage URL-ul paginii următoare din HTML.
        Verifică: rel=next, a[rel=next], pagina=N+1 prezent în navigație.
        """
        # 1. <link rel="next">
        link = soup.find("link", rel="next")
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                href = BASE_URL + href
            return self.canonicalize_url(href)

        # 2. <a rel="next">
        a_next = soup.find("a", rel="next")
        if a_next and a_next.get("href"):
            href = a_next["href"]
            if href.startswith("/"):
                href = BASE_URL + href
            return self.canonicalize_url(href)

        # 3. Verificăm dacă pagina N+1 există în navigație
        parsed = urlparse(current_url)
        params: dict[str, str] = {}
        for part in (parsed.query or "").split("&"):
            if "=" in part:
                k, _, v = part.partition("=")
                params[k] = v

        current_page = int(params.get("pagina", "1"))
        next_page = str(current_page + 1)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"pagina={next_page}" in href or f"pagina/{next_page}" in href:
                params["pagina"] = next_page
                new_qs = "&".join(f"{k}={v}" for k, v in params.items())
                return urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path, "", new_qs, ""
                ))

        return None

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover_listing_refs(self, html: str) -> list[str]:
        """
        Extrage URL-urile anunțurilor dintr-o pagină de rezultate.
        Strategie: JSON-LD (@graph listing nodes) → HTML fallback (item-\\d+).
        """
        soup = BeautifulSoup(html, "html.parser")
        refs: list[str] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()

        # ── JSON-LD primary ────────────────────────────────────────────────
        listing_nodes = [n for n in iter_jsonld_nodes(soup) if is_listing_node(n)]

        for node in listing_nodes:
            ext_id = self._extract_external_id_from_node(node)
            if ext_id and ext_id in seen_ids:
                continue

            url = self.extract_listing_url(node, soup, ext_id)
            if url and url not in seen_urls:
                seen_urls.add(url)
                if ext_id:
                    seen_ids.add(ext_id)
                refs.append(url)

        # ── HTML fallback ──────────────────────────────────────────────────
        if not refs:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not re.search(r"item-\d+", href):
                    continue
                if href.startswith("/"):
                    href = BASE_URL + href
                if "imobiliare.ro" not in href:
                    continue
                canonical = self.canonicalize_url(href)
                if canonical not in seen_urls:
                    seen_urls.add(canonical)
                    refs.append(canonical)

        return refs

    # ── JSON-LD extractori ────────────────────────────────────────────────────

    def extract_jsonld_title(self, node: dict) -> str | None:
        for key in ("name", "headline", "title"):
            val = node.get(key)
            if val and isinstance(val, str):
                return val.strip() or None
        return None

    def extract_jsonld_description(self, node: dict) -> str | None:
        val = node.get("description")
        if val and isinstance(val, str):
            return val.strip()[:5000] or None
        return None

    def extract_jsonld_price(self, node: dict) -> float | None:
        offers = node.get("offers") or {}
        if not isinstance(offers, dict):
            return None

        # offers.priceSpecification.price
        price_spec = offers.get("priceSpecification") or {}
        if isinstance(price_spec, dict):
            price = price_spec.get("price")
            if price is not None:
                return self._parse_float(price)

        # offers.price
        price = offers.get("price")
        if price is not None:
            return self._parse_float(price)

        return None

    def extract_jsonld_currency(self, node: dict) -> str | None:
        offers = node.get("offers") or {}
        if not isinstance(offers, dict):
            return None

        price_spec = offers.get("priceSpecification") or {}
        if isinstance(price_spec, dict):
            cur = price_spec.get("priceCurrency")
            if cur:
                return str(cur).upper()

        cur = offers.get("priceCurrency")
        if cur:
            return str(cur).upper()

        return None

    def extract_jsonld_images(self, node: dict) -> list[str]:
        """Suportă string, ImageObject, și liste ale acestora."""
        images = node.get("image")
        if not images:
            return []

        def _img_url(item: Any) -> str | None:
            if isinstance(item, str):
                return item if item.startswith("http") else None
            if isinstance(item, dict):
                url = item.get("url") or item.get("contentUrl") or item.get("src")
                if url and isinstance(url, str) and url.startswith("http"):
                    return url
            return None

        if isinstance(images, list):
            return [u for item in images for u in [_img_url(item)] if u]
        url = _img_url(images)
        return [url] if url else []

    def extract_jsonld_address(self, node: dict) -> dict | None:
        addr = node.get("address")
        if isinstance(addr, dict):
            return addr
        return None

    def extract_jsonld_locality(self, node: dict) -> str | None:
        """Extrage numele localității din address sau câmpuri directe."""
        addr = self.extract_jsonld_address(node)
        if addr:
            for key in ("addressLocality", "addressCity", "locality"):
                val = addr.get(key)
                if val and isinstance(val, str):
                    return val.strip() or None

        for key in ("addressLocality", "locality", "city"):
            val = node.get(key)
            if val and isinstance(val, str):
                return val.strip() or None

        return None

    def extract_jsonld_zone(self, node: dict) -> str | None:
        """Extrage zona/cartierul din address."""
        addr = self.extract_jsonld_address(node)
        if addr:
            # streetAddress e mai granular — poate fi zona/cartier
            street = addr.get("streetAddress")
            if street and isinstance(street, str) and street.strip():
                return street.strip()
        return None

    def extract_jsonld_published_at(self, node: dict) -> datetime | None:
        for key in ("datePublished", "dateCreated", "publishedAt"):
            val = node.get(key)
            if val:
                return self._parse_date(val)
        return None

    def extract_jsonld_updated_at(self, node: dict) -> datetime | None:
        for key in ("dateModified", "updatedAt", "lastModified"):
            val = node.get(key)
            if val:
                return self._parse_date(val)
        return None

    def extract_jsonld_seller(
        self, node: dict
    ) -> tuple[str, str | None, str | None, str, str]:
        """
        Returnează (seller_type, seller_name, agency_name, confidence, source).
        Detectare din @type JSON-LD sau câmpuri directe.
        """
        seller_node = node.get("seller") or node.get("agent") or node.get("author")

        if isinstance(seller_node, dict):
            seller_type_raw = str(seller_node.get("@type") or "").lower()
            name = seller_node.get("name") or seller_node.get("legalName")
            if isinstance(name, dict):
                name = name.get("name") or name.get("legalName")

            if "person" in seller_type_raw:
                return "private", name, None, "high", "jsonld_type"

            if "realestateagent" in seller_type_raw or ("agent" in seller_type_raw and "organization" not in seller_type_raw):
                return "agency", name, name, "high", "jsonld_type"

            if "organization" in seller_type_raw:
                additional = str(seller_node.get("additionalType") or "").lower()
                if "developer" in additional or "constructor" in additional or "dezvoltator" in additional:
                    return "developer", name, None, "medium", "jsonld_type"
                return "agency", name, name, "medium", "jsonld_type"

        # Fallback: câmpuri directe (stil vechi sau custom)
        return self._parse_seller_from_fields(node)

    def _parse_seller_from_fields(self, data: dict) -> tuple[str, str | None, str | None, str, str]:
        """Fallback: parsare seller din câmpuri directe."""
        vanzator = data.get("vanzator") or data.get("seller") or {}
        if not isinstance(vanzator, dict):
            return "unknown", None, None, "low", "missing"

        tip = str(vanzator.get("tip") or vanzator.get("type") or vanzator.get("tipVanzator") or "").upper()
        name = vanzator.get("nume") or vanzator.get("name")
        agency = vanzator.get("agentie") or vanzator.get("agency")

        agency_name = None
        if isinstance(agency, dict):
            agency_name = agency.get("name") or agency.get("denumire")
        elif isinstance(agency, str) and agency:
            agency_name = agency

        if any(k in tip for k in ("AGENTIE", "AGENCY", "IMOBILIAR", "AGENT")):
            return "agency", name, agency_name or name, "high", "tip_field"
        if any(k in tip for k in ("CONSTRUCTOR", "DEVELOPER", "DEZVOLTATOR")):
            return "developer", name, None, "high", "tip_field"
        if any(k in tip for k in ("PERSOANA_FIZICA", "PRIVAT", "PRIVATE", "FIZICA", "PF")):
            return "private", name, None, "high", "tip_field"
        if agency_name:
            return "agency", name, agency_name, "medium", "agency_present"

        return "unknown", name, None, "low", "insufficient_data"

    # ── Parse from JSON-LD ────────────────────────────────────────────────────

    def _parse_from_jsonld(
        self, node: dict, url: str, soup: BeautifulSoup
    ) -> ScrapedListing | None:
        """Construiește ScrapedListing dintr-un nod JSON-LD de listing."""
        try:
            external_id = self._extract_external_id_from_node(node) or self.extract_external_id(url)
            canonical_url = self.canonicalize_url(url)

            title = self.extract_jsonld_title(node)
            description = self.extract_jsonld_description(node)
            price_raw = self.extract_jsonld_price(node)
            currency = self.extract_jsonld_currency(node)
            images = self.extract_jsonld_images(node)
            location_raw = self.extract_jsonld_locality(node)
            zone_raw = self.extract_jsonld_zone(node)
            published_at = self.extract_jsonld_published_at(node)
            updated_at_source = self.extract_jsonld_updated_at(node)
            seller_type, seller_name, agency_name, st_confidence, st_source = (
                self.extract_jsonld_seller(node)
            )

            # Preț: separă EUR de RON
            if currency == "EUR" and price_raw is not None:
                price_eur = price_raw
                original_price = price_raw
                original_currency = "EUR"
            elif currency == "RON" and price_raw is not None:
                price_eur = None  # normalize_listing va converti
                original_price = price_raw
                original_currency = "RON"
            elif price_raw is not None:
                # Presupunem EUR dacă moneda nu e specificată
                price_eur = price_raw
                original_price = price_raw
                original_currency = None
            else:
                price_eur = None
                original_price = None
                original_currency = None

            # Câmpuri numerice suplimentare
            rooms = self._parse_int(node.get("numberOfRooms") or node.get("nrCamere"))

            floor_size = node.get("floorSize")
            if isinstance(floor_size, dict):
                surface_m2 = self._parse_float(floor_size.get("value"))
            else:
                surface_m2 = self._parse_float(floor_size or node.get("suprafata"))

            floor = self._parse_int(node.get("floorLevel") or node.get("etaj"))
            construction_year = self._parse_int(node.get("yearBuilt") or node.get("anConstructie"))

            return ScrapedListing(
                title=title or f"Anunț {external_id}",
                url=url,
                description=description,
                price_eur=price_eur,
                original_price=original_price,
                original_currency=original_currency,
                rooms=rooms,
                surface_m2=surface_m2,
                location_raw=location_raw,
                locality_raw=location_raw,
                zone_raw=zone_raw,
                image_urls=images,
                image_count=len(images),
                main_image_url=images[0] if images else None,
                seller_type=seller_type,
                seller_name=seller_name,
                agency_name=agency_name,
                seller_type_confidence=st_confidence,
                seller_type_source=st_source,
                published_at=published_at,
                updated_at_source=updated_at_source,
                external_id=external_id,
                canonical_url=canonical_url,
                floor=floor,
                construction_year=construction_year,
            )
        except Exception as exc:
            logger.error("Eroare la parsare JSON-LD listing %s: %s", url[:80], exc)
            return None

    # ── Fetch listing ─────────────────────────────────────────────────────────

    def fetch_listing(self, url: str, client: httpx.Client | None = None) -> dict | None:
        close_client = False
        if client is None:
            client = self._make_client()
            close_client = True

        try:
            html, status = self._fetch_with_retry(client, url)
            if status == 404:
                return None
            return {"html": html, "url": url, "status_code": status}
        finally:
            if close_client:
                client.close()

    # ── Parse listing ─────────────────────────────────────────────────────────

    def parse_listing(self, raw: dict) -> ScrapedListing | None:
        """
        Parsează datele raw dintr-o pagină de detaliu în ScrapedListing.
        Prioritate: JSON-LD → HTML fallback.
        """
        if not raw:
            return None

        url = raw.get("url", "")
        html = raw.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        # Găsim nodul JSON-LD cel mai relevant
        ext_id_from_url = self.extract_external_id(url)
        best_node: dict | None = None

        for node in iter_jsonld_nodes(soup):
            if not is_listing_node(node):
                continue
            node_ext_id = self._extract_external_id_from_node(node)
            if node_ext_id and node_ext_id == ext_id_from_url:
                best_node = node
                break
            if best_node is None:
                best_node = node

        if best_node:
            return self._parse_from_jsonld(best_node, url, soup)

        return self._parse_from_html(html, url)

    # ── HTML fallback ─────────────────────────────────────────────────────────

    def _parse_from_html(self, html: str, url: str) -> ScrapedListing | None:
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            title_text = h1.get_text(strip=True) if h1 else None
            if not title_text:
                return None
            external_id = self.extract_external_id(url)
            return ScrapedListing(
                title=title_text,
                url=url,
                description=None,
                price_eur=None,
                rooms=None,
                surface_m2=None,
                location_raw=None,
                image_urls=[],
                external_id=external_id,
                canonical_url=self.canonicalize_url(url),
                data_quality="warning",
                quality_warnings=["jsonld_missing", "html_fallback"],
            )
        except Exception:
            return None

    # ── Parse helpers ─────────────────────────────────────────────────────────

    def _parse_date(self, val: Any) -> datetime | None:
        if val is None:
            return None
        val_str = str(val).strip()

        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(val_str, fmt)
            except ValueError:
                continue

        if val_str.isdigit() and len(val_str) in (10, 13):
            try:
                ts = int(val_str)
                if len(val_str) == 13:
                    ts //= 1000
                return datetime.utcfromtimestamp(ts)
            except (ValueError, OSError):
                pass

        now = datetime.utcnow()
        val_lower = val_str.lower()
        if "azi" in val_lower or "today" in val_lower:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if "ieri" in val_lower or "yesterday" in val_lower:
            return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        m = re.search(r"acum\s+(\d+)\s+or[eă]", val_lower)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        m = re.search(r"acum\s+(\d+)\s+zile?", val_lower)
        if m:
            return now - timedelta(days=int(m.group(1)))

        return None

    def _parse_float(self, val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(str(val).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            return None

    def _parse_int(self, val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(float(str(val)))
        except (ValueError, TypeError):
            return None

    # ── Normalize listing ─────────────────────────────────────────────────────

    def normalize_listing(self, listing: ScrapedListing) -> ScrapedListing:
        """Post-procesare: curăță localitate, convertește RON→EUR, setează calitate."""
        if listing.location_raw:
            listing.location_raw = listing.location_raw.strip()
            if listing.zone_raw is None:
                for sep in (" - ", " / ", ", "):
                    if sep in listing.location_raw:
                        parts = listing.location_raw.split(sep, 1)
                        listing.location_raw = parts[0].strip()
                        listing.zone_raw = parts[1].strip()
                        break

        if listing.price_eur is None and listing.original_price and listing.original_currency == "RON":
            ron_rate = 5.0
            listing.price_eur = round(listing.original_price / ron_rate, 2)
            listing.quality_warnings.append("pret_convertit_din_ron")
            listing.data_quality = "warning"

        if not listing.title or len(listing.title) < 5:
            listing.quality_warnings.append("titlu_lipsa")
            listing.data_quality = "warning"

        if listing.price_eur is None:
            listing.quality_warnings.append("pret_lipsa")
            listing.data_quality = "warning"

        if not listing.location_raw:
            listing.quality_warnings.append("localitate_lipsa")
            listing.data_quality = "warning"

        return listing

    # ── Pagina de rezultate cu JSON (structura 2026) ──────────────────────────

    @staticmethod
    def _inertia_page(html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        node = soup.find(id="app") or soup.find(attrs={"data-page": True})
        raw = node.get("data-page") if node else None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _num(text) -> float | None:
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return float(text)
        m = re.search(r"\d[\d.,\s]*", str(text))
        if not m:
            return None
        tok = re.sub(r"\s", "", m.group(0)).rstrip(".,")
        # „52.000” / „1.250.000” → mii; „43,5” → zecimale
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
            tok = re.sub(r"[.,]", "", tok)
        else:
            tok = tok.replace(".", "").replace(",", ".")
        try:
            return float(tok)
        except ValueError:
            return None

    @staticmethod
    def _seller_from(raw: str | None) -> str:
        v = (raw or "").lower()
        if any(k in v for k in ("owner", "private", "proprietar", "particular", "person")):
            return "private"
        if "develop" in v or "dezvolt" in v:
            return "developer"
        if v:
            return "agency"
        return "unknown"

    def listings_from_result_page(
        self, html: str, prop_type: str, trans_type: str
    ) -> tuple[list[ScrapedListing], int | None] | None:
        """
        Extrage anunțurile din JSON-ul paginii de rezultate.
        Returnează (anunțuri, ultima_pagină) sau None dacă pagina nu are acest format.
        """
        page = self._inertia_page(html)
        if not page:
            return None
        props = page.get("props") or {}
        section = next(
            (s for s in props.get("sections") or [] if s.get("type") == "results-list"),
            None,
        )
        if section is None:
            return None
        last_page = (props.get("searchMeta") or {}).get("lastPage")

        out: list[ScrapedListing] = []
        for item in (section.get("data") or {}).get("listings") or []:
            try:
                ext_id = str(item.get("id") or "")
                url = item.get("url") or ""
                if not ext_id or not url:
                    continue
                if url.startswith("/"):
                    url = BASE_URL + url
                highlights = {
                    str(h.get("key") or ""): str(h.get("label") or "")
                    for h in item.get("highlights") or []
                }

                def hl(*needles: str, exclude: str = "") -> str | None:
                    for k, v in highlights.items():
                        if any(n in k for n in needles) and not (exclude and exclude in k):
                            return v
                    return None

                ga = ((item.get("tracking") or {}).get("ga4Item")) or {}
                price = self._num(item.get("price"))
                price_text = str(item.get("price") or "")
                currency = "RON" if re.search(r"lei|ron", price_text, re.I) else "EUR"
                if price is None and isinstance(ga.get("price"), (int, float)) and ga["price"] > 0:
                    price = float(ga["price"])

                usable = self._num(hl("usable", "built", "surface", exclude="land"))
                land = self._num(hl("land", "teren", "lot"))
                if prop_type == "land" and land is None:
                    land = usable
                rooms_val = self._num(hl("bedroom", "room"))
                year = self._num(hl("year"))

                location = str(item.get("location") or "")
                parts = [p.strip() for p in location.split(",") if p.strip()]
                city = parts[-1] if parts else None
                zone = ", ".join(parts[:-1]) if len(parts) > 1 else None

                title = item.get("title") or item.get("heading") or ""
                images = [i.get("src") for i in item.get("images") or [] if i.get("src")]
                warnings: list[str] = []
                quality = "valid"
                if price is None:
                    warnings.append("pret_lipsa")
                    quality = "warning"
                surface = land if prop_type == "land" else usable
                if surface is None:
                    warnings.append("suprafata_lipsa")
                    quality = "warning"

                out.append(ScrapedListing(
                    title=title,
                    url=url,
                    description=item.get("descriptionPreview"),
                    price_eur=price if currency == "EUR" else None,
                    rooms=int(rooms_val) if rooms_val and prop_type in ("apartment", "house") else None,
                    surface_m2=surface,
                    location_raw=city,
                    image_urls=images,
                    data_quality=quality,
                    quality_warnings=warnings,
                    zone_raw=zone,
                    external_id=ext_id,
                    canonical_url=url,
                    original_price=price,
                    original_currency=currency,
                    property_type=prop_type,
                    transaction_type=trans_type,
                    seller_type=self._seller_from(ga.get("sellerType")),
                    agency_name=item.get("agencyName"),
                    seller_type_source="ga4_seller_type",
                    county_raw="Alba",
                    usable_surface_m2=usable,
                    land_surface_m2=land,
                    construction_year=int(year) if year and 1800 < year < 2100 else None,
                    image_count=item.get("mediaCount"),
                    main_image_url=images[0] if images else None,
                ))
            except Exception as exc:  # un anunț stricat nu oprește pagina
                logger.warning("imobiliare.ro: anunț ignorat (%s)", exc)
        return out, (int(last_page) if last_page else None)

    def iter_batches(self, max_pages: int = 20):
        """
        Livrează câte o pagină de rezultate. Folosește JSON-ul din pagina de
        rezultate (rapid, fără cereri per anunț); dacă site-ul revine la vechiul
        format, cade pe fluxul clasic (scrape_all_legacy) pentru acea rulare.
        """
        if not settings.scrape_imobiliare_ro_enabled:
            raise ImobiliareRoNotAuthorizedError(
                "SCRAPE_IMOBILIARE_RO_ENABLED=false. Setează în .env pentru a activa."
            )
        if not settings.scrape_imobiliare_ro_authorized:
            raise ImobiliareRoNotAuthorizedError(
                "SCRAPE_IMOBILIARE_RO_AUTHORIZED=false. Setează în .env pentru a activa."
            )

        legacy_needed = False
        with self._make_client() as client:
            for prop_type, trans_type, path in INERTIA_CATEGORIES:
                seen: set[str] = set()
                last_page: int | None = None
                for page in range(1, max_pages + 1):
                    if last_page is not None and page > last_page:
                        break
                    url = f"{BASE_URL}/{path}" + (f"?page={page}" if page > 1 else "")
                    try:
                        html, _ = self._fetch_with_retry(client, url)
                    except ImobiliareRoBlockedError:
                        raise
                    except Exception as exc:
                        logger.error("imobiliare.ro: eroare la %s: %s", url[:80], exc)
                        break
                    parsed = self.listings_from_result_page(html, prop_type, trans_type)
                    if parsed is None:
                        if page == 1 and trans_type == "sale":
                            legacy_needed = True
                        break
                    listings, last_page = parsed
                    fresh = [l for l in listings if l.external_id not in seen]
                    seen.update(l.external_id for l in fresh)
                    if not fresh:
                        break
                    logger.info("imobiliare.ro: %s pagina %d — %d anunțuri", path, page, len(fresh))
                    yield fresh

        if legacy_needed:
            logger.warning("imobiliare.ro: pagina nu are JSON — folosesc fluxul vechi (mai lent)")
            yield self.scrape_all_legacy(max_pages=max_pages)

    # ── Scrape all ────────────────────────────────────────────────────────────

    def scrape_all(self, max_pages: int = 20) -> list[ScrapedListing]:
        """Toate anunțurile într-o listă (folosește iter_batches)."""
        results: list[ScrapedListing] = []
        for batch in self.iter_batches(max_pages=max_pages):
            results.extend(batch)
        return results

    def scrape_all_legacy(self, max_pages: int = 20) -> list[ScrapedListing]:
        """
        Flux vechi (JSON-LD + câte o cerere pentru fiecare anunț).
        Guard: ENABLED + AUTHORIZED obligatorii.
        """
        if not settings.scrape_imobiliare_ro_enabled:
            raise ImobiliareRoNotAuthorizedError(
                "SCRAPE_IMOBILIARE_RO_ENABLED=false. Setează în .env pentru a activa."
            )
        if not settings.scrape_imobiliare_ro_authorized:
            raise ImobiliareRoNotAuthorizedError(
                "SCRAPE_IMOBILIARE_RO_AUTHORIZED=false. Setează în .env pentru a activa."
            )

        results: list[ScrapedListing] = []
        logger.info("ImobiliareRoAdapter.scrape_all: start (max_pages=%d)", max_pages)

        with self._make_client() as client:
            for prop_type, trans_type, category_path in ALBA_CATEGORIES:
                logger.info("Categorie: %s", category_path)
                pages = self.discover_result_pages(category_path, max_pages)
                seen_listing_urls: set[str] = set()
                pages_processed = 0

                for page_url in pages:
                    try:
                        html, _ = self._fetch_with_retry(client, page_url)
                    except ImobiliareRoBlockedError:
                        logger.error("Blocat la %s — opresc categoria", page_url[:80])
                        raise
                    except Exception as exc:
                        logger.error("Eroare la pagina %s: %s", page_url[:80], exc)
                        break

                    listing_refs = self.discover_listing_refs(html)
                    if not listing_refs:
                        logger.info("Pagina %s fără listing-uri — stop paginator", page_url[:80])
                        break

                    new_refs = [r for r in listing_refs if r not in seen_listing_urls]
                    if not new_refs:
                        logger.info("Pagina %s repetă content — stop paginator", page_url[:80])
                        break

                    seen_listing_urls.update(new_refs)
                    pages_processed += 1
                    logger.info("Pagina %d: %d listing-uri noi", pages_processed, len(new_refs))

                    for listing_url in new_refs:
                        try:
                            raw = self.fetch_listing(listing_url, client)
                            if raw is None:
                                continue
                            parsed = self.parse_listing(raw)
                            if parsed is None:
                                continue
                            parsed.property_type = prop_type
                            parsed.transaction_type = trans_type
                            normalized = self.normalize_listing(parsed)
                            results.append(normalized)
                        except ImobiliareRoBlockedError:
                            raise
                        except Exception as exc:
                            logger.error("Eroare la listing %s: %s", listing_url[:80], exc)
                            continue

        logger.info("scrape_all: %d listing-uri din %d categorii", len(results), len(ALBA_CATEGORIES))
        return results
