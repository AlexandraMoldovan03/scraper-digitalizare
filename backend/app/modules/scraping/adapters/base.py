"""
SourceAdapter — contract comun pentru toți adaptori de scraping.

Fiecare sursă de anunțuri implementează această interfață.
Orchestratorul generic apelează scrape_all() fără să cunoască sursa concretă.
"""
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime


# ── Shared ScrapedListing ──────────────────────────────────────────────────────

@dataclass
class ScrapedListing:
    """
    Reprezentare normalizată a unui anunț extras din orice sursă.
    Null înseamnă "informație indisponibilă" — nu se inventează valori.
    """
    title: str
    url: str
    description: str | None
    price_eur: float | None
    rooms: int | None
    surface_m2: float | None
    location_raw: str | None
    image_urls: list[str]

    published_at: datetime | None = None
    data_quality: str = "valid"            # "valid" | "warning"
    quality_warnings: list[str] = field(default_factory=list)
    zone_raw: str | None = None
    zone_normalized: str | None = None

    # ── Câmpuri extinse ────────────────────────────────────────────────────────
    external_id: str | None = None
    canonical_url: str | None = None
    original_price: float | None = None
    original_currency: str | None = None
    property_type: str | None = None
    transaction_type: str | None = None
    seller_type: str | None = None          # private/agency/developer/unknown
    seller_name: str | None = None
    agency_name: str | None = None
    seller_type_confidence: str | None = None
    seller_type_source: str | None = None
    locality_raw: str | None = None
    county_raw: str | None = None           # ex: "Alba", "Cluj" — dezambiguizează localități omonime
    usable_surface_m2: float | None = None
    land_surface_m2: float | None = None
    floor: int | None = None
    total_floors: int | None = None
    construction_year: int | None = None
    property_condition: str | None = None
    building_type: str | None = None
    features: list[str] = field(default_factory=list)
    updated_at_source: datetime | None = None
    image_count: int | None = None
    main_image_url: str | None = None


# ── SourceAdapter ABC ──────────────────────────────────────────────────────────

class SourceAdapter(ABC):
    """
    Contract comun pentru adaptori de surse imobiliare.

    Metode obligatorii:
      source_key   — identificator unic (ex: "publi24", "imobiliare_ro")
      scrape_all() — descoperă + fetch + parse + normalize în bloc
      extract_external_id() — ID extern stabil din URL

    Metode opționale (progres granular):
      discover_result_pages()  — paginile de rezultate
      discover_listing_refs()  — URL-uri listing-uri dintr-o pagină
      fetch_listing()          — fetch raw pentru o pagină de detaliu
      parse_listing()          — raw → ScrapedListing
      normalize_listing()      — post-procesare localitate/zonă
    """

    @property
    @abstractmethod
    def source_key(self) -> str:
        """Identificator unic al sursei. Trebuie să coincidă cu Source.slug din DB."""
        ...

    @abstractmethod
    def scrape_all(self, max_pages: int = 20) -> list[ScrapedListing]:
        """
        Punct de intrare principal.
        Returnează lista completă de anunțuri procesate pentru o rulare.
        """
        ...

    def iter_batches(self, max_pages: int = 20) -> Iterator[list[ScrapedListing]]:
        """
        Livrează anunțurile pe loturi (de ex. câte o pagină de rezultate),
        ca orchestratorul să le salveze imediat în DB — anunțurile apar în
        aplicație pe parcurs, nu doar la finalul rulării.

        Implementarea implicită livrează totul într-un singur lot (compatibil
        cu adaptorii existenți care implementează doar scrape_all()).
        """
        yield self.scrape_all(max_pages=max_pages)

    @abstractmethod
    def extract_external_id(self, url: str) -> str:
        """
        Extrage identificatorul extern stabil din URL.
        Folosit pentru deduplicare (source_id + external_id).
        """
        ...

    def canonicalize_url(self, url: str) -> str:
        """
        Returnează forma canonică a URL-ului (fără parametri de tracking).
        Implementarea implicită: elimină query string.
        """
        return url.split("?")[0].rstrip("/")

    # ── Metode granulare (opționale, pentru progres real-time) ──────────────────

    def discover_result_pages(self, max_pages: int = 20) -> list[str]:
        """Returnează URL-urile paginilor de rezultate (pagina 1, 2, ...)."""
        return []

    def discover_listing_refs(self, page_url: str) -> list[str]:
        """Extrage URL-urile anunțurilor dintr-o pagină de rezultate."""
        return []

    def fetch_listing(self, url: str) -> dict | None:
        """Fetch + parse HTML raw pentru o singură pagină de detaliu."""
        return None

    def parse_listing(self, raw: dict) -> ScrapedListing | None:
        """Parsează datele raw într-un ScrapedListing."""
        return None

    def normalize_listing(self, listing: ScrapedListing) -> ScrapedListing:
        """Normalizează localitate, zonă, calitate. Returnează listing-ul modificat."""
        return listing
