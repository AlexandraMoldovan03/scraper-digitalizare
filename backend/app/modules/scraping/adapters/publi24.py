"""
Publi24Adapter — înfășoară implementarea existentă fără s-o modifice.

Deleghează scraping-ul complet către scrape_publi24_all_pages().
Nu schimbă comportamentul Publi24 — este un wrapper pur.
"""
from app.modules.scraping.adapters.base import ScrapedListing, SourceAdapter
from app.modules.scraping.publi24.scraper import iter_publi24_batches, scrape_publi24_all_pages


class Publi24Adapter(SourceAdapter):
    """Adapter pentru publi24.ro — județul Alba, toate categoriile imobiliare."""

    @property
    def source_key(self) -> str:
        return "publi24"

    def scrape_all(self, max_pages: int = 20) -> list[ScrapedListing]:
        """
        Apelează direct scrape_publi24_all_pages() — nicio logică adăugată.
        scraper.py importă ScrapedListing din adapters/base.py, deci tipul coincide.
        """
        return scrape_publi24_all_pages(max_pages=max_pages)

    def iter_batches(self, max_pages: int = 20):
        """
        Rapid: citește direct cardurile din paginile de rezultate (apartamente,
        case, terenuri, spații — vânzare și închiriere), fără cererea per anunț.
        Vânzătorul (proprietar/agenție) vine din card.
        """
        yield from iter_publi24_batches(max_pages=max_pages)

    def extract_external_id(self, url: str) -> str:
        """
        Publi24 URL: .../anunturi/.../anunt-XXXXX.html
        External ID = slug fără extensia .html.
        """
        return url.rstrip("/").split("/")[-1].replace(".html", "")

    def canonicalize_url(self, url: str) -> str:
        """Elimină query string + fragment; păstrează slug-ul anunțului."""
        return url.split("?")[0].split("#")[0].rstrip("/")
