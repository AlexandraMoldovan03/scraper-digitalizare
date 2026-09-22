"""
StoriaAdapter — storia.ro (Alba).

Strategie: Storia e o aplicatie Next.js care embed-eaza datele complete de
listing in <script id="__NEXT_DATA__">. Citim JSON-ul direct din pagina de
rezultate — nu deschidem fiecare anunt separat.

Avantaje fata de parsarea HTML:
  - campuri tipizate (pret, suprafata, camere vin ca numere, nu ca text)
  - un singur request per pagina de rezultate (~37 anunturi), nu 1+37
  - nu se strica la schimbari de CSS/markup

robots.txt (verificat): /ro/rezultate/ si /ro/oferta/ sunt permise
(fisierul se termina cu "Allow: /"). /hpr/ este Disallow — excludem
explicit acele URL-uri.
"""
import json
import logging
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.modules.scraping.adapters.base import ScrapedListing, SourceAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.storia.ro"

# Categorii scanate pentru judetul Alba
# (property_type, transaction_type, path)
ALBA_CATEGORIES = [
    ("apartment", "sale", "vanzare/apartament/alba"),
    ("house",     "sale", "vanzare/casa/alba"),
    ("land",      "sale", "vanzare/teren/alba"),
    ("apartment", "rent", "inchiriere/apartament/alba"),
    ("house",     "rent", "inchiriere/casa/alba"),
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
}

# Cai interzise de robots.txt
DISALLOWED_PREFIXES = ("/hpr/",)

# Nivelurile de localizare din reverseGeocoding
# ATENTIE: address.city.name poate fi un CARTIER (ex. "Ampoi 3"),
# de aceea folosim ierarhia din reverseGeocoding pentru localitate.
LOCALITY_LEVELS = (
    "county_capital", "city", "town", "municipality",
    "commune", "village", "locality",
)
ZONE_LEVELS = ("district", "subdistrict", "neighbourhood", "quarter")

# Storia trimite numarul de camere ca enum text, nu ca numar
ROOMS_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
}

ESTATE_MAP = {
    "FLAT": "apartment",
    "HOUSE": "house",
    "TERRAIN": "land",
    "COMMERCIAL": "commercial",
    "GARAGE": "garage",
    "ROOM": "room",
}

TRANSACTION_MAP = {
    "SELL": "sale",
    "RENT": "rent",
}


def _strip_for_compare(text: str) -> str:
    """Normalizare minimala pentru comparat nume de judet."""
    unified = text.replace("î", "â").replace("Î", "Â")
    decomposed = unicodedata.normalize("NFKD", unified)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return plain.replace("ș", "s").replace("ț", "t").strip().lower()


class StoriaBlockedError(RuntimeError):
    """Storia a refuzat cererea sau a returnat o pagina fara date."""


class StoriaAdapter(SourceAdapter):
    """Adapter pentru storia.ro — judetul Alba."""

    # ── Contract SourceAdapter ────────────────────────────────────────────────

    @property
    def source_key(self) -> str:
        return "storia"

    def extract_external_id(self, url: str) -> str:
        """
        Storia pune un ID alfanumeric la finalul slug-ului: ...-IDHGMQ
        Preferam ID-ul numeric din JSON (vezi _parse_item); asta e fallback
        pentru cazul in care avem doar URL-ul.
        """
        m = re.search(r"-ID([A-Za-z0-9]+)(?:\.html)?/?$", url)
        if m:
            return f"ID{m.group(1)}"
        return url.rstrip("/").split("/")[-1]

    def canonicalize_url(self, url: str) -> str:
        return url.split("?")[0].split("#")[0].rstrip("/")

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _fetch_next_data(self, client: httpx.Client, url: str) -> dict | None:
        """
        Descarca pagina si extrage JSON-ul din __NEXT_DATA__.
        Returneaza None daca pagina nu exista (404).
        Ridica StoriaBlockedError daca suntem blocati.
        """
        resp = client.get(url)

        if resp.status_code == 404:
            logger.info("Storia: 404 la %s — categoria nu exista", url)
            return None

        if resp.status_code in (401, 403, 429):
            raise StoriaBlockedError(
                f"Storia a returnat {resp.status_code} la {url[:90]}"
            )

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        node = soup.find("script", id="__NEXT_DATA__")
        if node is None or not node.string:
            raise StoriaBlockedError(
                f"__NEXT_DATA__ lipseste la {url[:90]} — posibil bot-check"
            )

        try:
            return json.loads(node.string)
        except json.JSONDecodeError as exc:
            raise StoriaBlockedError(f"__NEXT_DATA__ invalid la {url[:90]}: {exc}")

    @staticmethod
    def _items_from(data: dict) -> list[dict]:
        """Extrage lista de anunturi din structura __NEXT_DATA__."""
        try:
            items = data["props"]["pageProps"]["data"]["searchAds"]["items"]
            return items if isinstance(items, list) else []
        except (KeyError, TypeError):
            return []

    @staticmethod
    def _total_pages(data: dict) -> int | None:
        """Numarul total de pagini, daca Storia il expune."""
        try:
            pag = data["props"]["pageProps"]["data"]["searchAds"]["pagination"]
            for key in ("totalPages", "pageCount", "total_pages"):
                if isinstance(pag.get(key), int):
                    return pag[key]
        except (KeyError, TypeError):
            pass
        return None

    # ── Helpers de parsare ────────────────────────────────────────────────────

    @staticmethod
    def _money(node) -> tuple[float | None, str | None]:
        """
        Normalizeaza un camp de pret.
        Storia foloseste {"value": 95000, "currency": "EUR"}, dar tolerăm
        si un numar simplu, ca sa nu crape daca schimba forma.
        """
        if node is None:
            return None, None
        if isinstance(node, (int, float)):
            return float(node), None
        if isinstance(node, dict):
            val = node.get("value")
            cur = node.get("currency")
            if val is None:
                return None, cur
            try:
                return float(val), (str(cur).upper() if cur else None)
            except (TypeError, ValueError):
                return None, cur
        return None, None

    @staticmethod
    def _number(value) -> float | None:
        """Converteste la float, tolerand string-uri de tip '65,7'."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", ".").strip()
            m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
            if m:
                try:
                    return float(m.group(0))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _rooms(value) -> int | None:
        """
        roomsNumber vine ca enum text ("TWO", "THREE"), nu ca numar.
        Toleram si forme numerice sau "ROOMS_2", in caz ca schimba formatul.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)

        text = str(value).strip().upper()
        if not text:
            return None

        if text in ROOMS_WORDS:
            return ROOMS_WORDS[text]

        # "MORE" / "TEN_PLUS" — nu putem sti exact
        if "MORE" in text:
            return None

        m = re.search(r"\d+", text)
        if m:
            return int(m.group(0))

        logger.warning("Storia: roomsNumber necunoscut: %r", value)
        return None

    @classmethod
    def _floor(cls, value) -> int | None:
        """floorNumber poate fi int, 'FLOOR_3', 'GROUND' sau 'PARTER'."""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        text = str(value).upper()
        if "GROUND" in text or "PARTER" in text:
            return 0
        if "BASEMENT" in text or "SUBSOL" in text:
            return -1
        m = re.search(r"\d+", text)
        return int(m.group(0)) if m else None

    @staticmethod
    def _county(location: dict | None) -> str | None:
        """
        Extrage judetul. Storia il da in doua locuri:
          reverseGeocoding.locations[locationLevel="county"].name -> "Alba"
          address.province.name                                  -> "Alba (judet)"

        Cautarile pe Alba returneaza si anunturi din judete vecine (Cluj,
        Mures, Sibiu), iar 251 de nume de localitati se repeta intre judete.
        Fara judet, "Stejeris" e ambiguu intre Cluj si Mures.
        """
        if not isinstance(location, dict):
            return None

        geo = location.get("reverseGeocoding") or {}
        for loc in geo.get("locations") or []:
            if isinstance(loc, dict) and str(loc.get("locationLevel") or "").lower() == "county":
                name = loc.get("name")
                if name:
                    return str(name).strip()

        province = (location.get("address") or {}).get("province") or {}
        name = province.get("name") if isinstance(province, dict) else None
        if name:
            # "Alba (judet)" -> "Alba"
            return re.sub(r"\s*\(jude[țt]\)\s*$", "", str(name), flags=re.I).strip()

        return None

    @classmethod
    def _locality_and_zone(cls, location: dict | None) -> tuple[str | None, str | None]:
        """
        Determina (localitate, zona) din blocul location.

        reverseGeocoding.locations vine ordonat de la general la specific:
          county -> county_capital -> district
        Luam ultima potrivire pe nivel de localitate si, separat, cartierul.

        Nu folosim address.city.name ca sursa primara: acolo Storia pune
        uneori cartierul (ex. "Ampoi 3"), ceea ce ar strica match-ul cu
        tabela cities.
        """
        if not isinstance(location, dict):
            return None, None

        locality = zone = None

        geo = location.get("reverseGeocoding") or {}
        for loc in geo.get("locations") or []:
            if not isinstance(loc, dict):
                continue
            level = str(loc.get("locationLevel") or "").lower()
            name = loc.get("name")
            if not name:
                continue
            if level in LOCALITY_LEVELS:
                locality = name
            elif level in ZONE_LEVELS:
                zone = name

        # Fallback pe adresa structurata
        address = location.get("address") or {}
        if not locality:
            city = (address.get("city") or {}).get("name")
            if city:
                locality = city
        if not zone:
            street = address.get("street")
            if isinstance(street, dict):
                zone = street.get("name")
            elif isinstance(street, str):
                zone = street

        return locality, zone

    @classmethod
    def _seller(cls, item: dict) -> tuple[str, str | None]:
        """Returneaza (seller_type, agency_name)."""
        agency = item.get("agency") if isinstance(item.get("agency"), dict) else None
        agency_name = agency.get("name") if agency else None

        if item.get("isPrivateOwner") is True:
            return "private", None

        raw = str(
            item.get("extendedAdvertiserType")
            or item.get("advertOwner")
            or ""
        ).upper()

        if "DEVELOPER" in raw:
            return "developer", agency_name
        if "AGENCY" in raw or "BUSINESS" in raw:
            return "agency", agency_name
        if "PRIVATE" in raw:
            return "private", None
        return ("agency", agency_name) if agency_name else ("unknown", None)

    @staticmethod
    def _published(item: dict) -> datetime | None:
        for key in ("dateCreated", "createdAtFirst", "pushedUpAt"):
            raw = item.get(key)
            if not raw:
                continue
            text = str(raw).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text).replace(tzinfo=None)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(str(raw)[:19], fmt)
                    except ValueError:
                        continue
        return None

    @staticmethod
    def _images(item: dict) -> list[str]:
        out: list[str] = []
        for img in item.get("images") or []:
            if isinstance(img, dict):
                url = img.get("large") or img.get("medium")
                if url and url not in out:
                    out.append(url)
            elif isinstance(img, str) and img not in out:
                out.append(img)
        return out

    # ── Parsare item ──────────────────────────────────────────────────────────

    def _parse_item(
        self,
        item: dict,
        default_property_type: str,
        default_transaction: str,
    ) -> ScrapedListing | None:
        href = item.get("href") or ""
        slug = item.get("slug") or ""

        if not href and slug:
            href = f"/ro/oferta/{slug}"
        if not href:
            return None

        # robots.txt: /hpr/ este Disallow
        if any(href.startswith(p) for p in DISALLOWED_PREFIXES):
            logger.debug("Storia: sar peste %s (Disallow in robots.txt)", href[:70])
            return None

        url = urljoin(BASE_URL, href)

        title = (item.get("title") or "").strip()
        if not title:
            return None

        # Pret
        price_value, currency = self._money(item.get("totalPrice"))
        if price_value is None:
            price_value, currency = self._money(item.get("rentPrice"))

        price_eur = price_value if (currency or "EUR") == "EUR" else None

        warnings: list[str] = []
        if item.get("hidePrice") is True or price_value is None:
            warnings.append("missing_price")
        if price_value is not None and currency and currency != "EUR":
            warnings.append(f"price_in_{currency.lower()}")

        estate = str(item.get("estate") or "").upper()
        property_type = ESTATE_MAP.get(estate, default_property_type)
        is_land = property_type == "land"

        land_surface = self._number(item.get("terrainAreaInSquareMeters"))
        surface = self._number(item.get("areaInSquareMeters"))
        if surface is None and is_land:
            # La teren, suprafata relevanta este cea de teren
            surface = land_surface
        if surface is None:
            warnings.append("missing_surface")

        rooms_int = self._rooms(item.get("roomsNumber"))
        # Terenurile nu au camere — absenta lor nu e o lipsa de date
        if rooms_int is None and not is_land:
            warnings.append("missing_rooms")

        locality, zone = self._locality_and_zone(item.get("location"))
        if not locality:
            warnings.append("missing_locality")

        county = self._county(item.get("location"))
        if county and _strip_for_compare(county) != "alba":
            # Anunt din alt judet, aparut in căutarea pe Alba
            warnings.append(f"outside_alba_{_strip_for_compare(county)}")

        seller_type, agency_name = self._seller(item)
        images = self._images(item)

        transaction = str(item.get("transaction") or "").upper()

        external_id = str(item["id"]) if item.get("id") is not None else self.extract_external_id(url)

        return ScrapedListing(
            title=title,
            url=url,
            description=item.get("shortDescription"),
            price_eur=price_eur,
            rooms=rooms_int,
            surface_m2=surface,
            location_raw=locality,
            image_urls=images,
            published_at=self._published(item),
            data_quality="warning" if warnings else "valid",
            quality_warnings=warnings,
            zone_raw=zone,
            zone_normalized=zone,
            external_id=external_id,
            canonical_url=self.canonicalize_url(url),
            original_price=price_value,
            original_currency=currency,
            property_type=property_type,
            transaction_type=TRANSACTION_MAP.get(transaction, default_transaction),
            seller_type=seller_type,
            agency_name=agency_name,
            seller_type_source="storia_json",
            seller_type_confidence="high" if item.get("isPrivateOwner") is not None else "medium",
            locality_raw=locality,
            county_raw=county,
            floor=self._floor(item.get("floorNumber")),
            land_surface_m2=land_surface,
            image_count=len(images),
            main_image_url=images[0] if images else None,
        )

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _scrape_category(
        self,
        client: httpx.Client,
        path: str,
        property_type: str,
        transaction: str,
        max_pages: int,
        delay: float,
    ) -> list[ScrapedListing]:
        results: list[ScrapedListing] = []
        for page_listings in self._iter_category(
            client, path, property_type, transaction, max_pages, delay
        ):
            results.extend(page_listings)
        return results

    def _iter_category(
        self,
        client: httpx.Client,
        path: str,
        property_type: str,
        transaction: str,
        max_pages: int,
        delay: float,
    ):
        """Generator: livrează anunțurile noi de pe fiecare pagină de rezultate."""
        results_count = 0
        seen_ids: set[str] = set()
        total_pages: int | None = None

        for page in range(1, max_pages + 1):
            # limit=72 → jumătate din cereri față de pagina implicită (36)
            url = f"{BASE_URL}/ro/rezultate/{path}?limit=72"
            if page > 1:
                url = f"{url}&page={page}"

            try:
                data = self._fetch_next_data(client, url)
            except StoriaBlockedError:
                raise
            except Exception as exc:
                logger.warning("Storia: eroare la %s: %s", url[:80], exc)
                break

            if data is None:
                break

            if total_pages is None:
                total_pages = self._total_pages(data)

            items = self._items_from(data)
            if not items:
                logger.info("Storia: %s pagina %d — 0 anunturi, opresc", path, page)
                break

            page_listings: list[ScrapedListing] = []
            for item in items:
                listing = self._parse_item(item, property_type, transaction)
                if listing is None:
                    continue
                if listing.external_id in seen_ids:
                    continue
                seen_ids.add(listing.external_id)
                page_listings.append(listing)
            results_count += len(page_listings)

            logger.info(
                "Storia: %s pagina %d — %d anunturi noi (total %d)",
                path, page, len(page_listings), results_count,
            )

            if not page_listings:
                break
            yield page_listings

            if total_pages is not None and page >= total_pages:
                break

            time.sleep(delay)

    def scrape_all(self, max_pages: int = 20) -> list[ScrapedListing]:
        deduped: dict[str, ScrapedListing] = {}
        for batch in self.iter_batches(max_pages=max_pages):
            for listing in batch:
                deduped.setdefault(listing.external_id or listing.url, listing)
        logger.info("Storia: total %d anunturi unice", len(deduped))
        return list(deduped.values())

    def iter_batches(self, max_pages: int = 20):
        """Livrează câte o pagină de rezultate — salvată imediat de orchestrator."""
        from app.core.config import settings

        if not getattr(settings, "scrape_storia_enabled", False):
            raise RuntimeError(
                "SCRAPE_STORIA_ENABLED=false in config. "
                "Seteaza in .env pentru a activa."
            )

        delay = float(getattr(settings, "storia_request_delay_seconds", 1.5))
        timeout = int(getattr(settings, "storia_request_timeout_seconds", 30))

        seen: set[str] = set()

        with httpx.Client(
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            for property_type, transaction, path in ALBA_CATEGORIES:
                logger.info("Storia: incep categoria %s", path)
                try:
                    for page_listings in self._iter_category(
                        client=client,
                        path=path,
                        property_type=property_type,
                        transaction=transaction,
                        max_pages=max_pages,
                        delay=delay,
                    ):
                        # Deduplicare globala (acelasi anunt poate aparea in doua categorii)
                        fresh = [
                            l for l in page_listings
                            if (l.external_id or l.url) not in seen
                        ]
                        seen.update(l.external_id or l.url for l in fresh)
                        if fresh:
                            yield fresh
                except StoriaBlockedError as exc:
                    # Blocaj real: oprim tot, nu insistam
                    logger.error("Storia: blocat — %s", exc)
                    raise
                except Exception as exc:
                    # O categorie stricata nu trebuie sa opreasca restul
                    logger.error("Storia: categoria %s a esuat: %s", path, exc)
                    continue

                time.sleep(delay)
