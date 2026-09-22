"""
Teste pentru ImobiliareRoAdapter — toate pe fixture-uri locale.
Nicio dependență de rețea.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "imobiliare_ro"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def make_soup(name: str) -> BeautifulSoup:
    return BeautifulSoup(load_fixture(name), "html.parser")


def raw(html: str, url: str = "https://www.imobiliare.ro/test/item-111111111") -> dict:
    return {"html": html, "url": url, "status_code": 200}


# ── Engine SQLite in-memory ───────────────────────────────────────────────────

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="source")
def source_fixture(session):
    from app.modules.market.models import Source
    src = Source(
        name="Imobiliare.ro",
        slug="imobiliare_ro",
        base_url="https://www.imobiliare.ro",
        is_active=True,
    )
    session.add(src)
    session.commit()
    session.refresh(src)
    return src


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 1: Structura adaptorului
# ══════════════════════════════════════════════════════════════════════════════

def test_registry_includes_imobiliare_ro():
    from app.modules.scraping.registry import get_adapter, is_registered
    assert is_registered("imobiliare_ro")
    adapter = get_adapter("imobiliare_ro")
    assert adapter.source_key == "imobiliare_ro"


def test_adapter_contract():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    for method in [
        "source_key", "scrape_all", "extract_external_id", "canonicalize_url",
        "detect_block_page", "discover_result_pages", "discover_listing_refs",
        "fetch_listing", "parse_listing", "normalize_listing",
        "extract_listing_url", "extract_next_page_url",
        "extract_jsonld_title", "extract_jsonld_price", "extract_jsonld_currency",
        "extract_jsonld_images", "extract_jsonld_locality", "extract_jsonld_updated_at",
    ]:
        assert hasattr(adapter, method), f"Metoda lipsă: {method}"


def test_canonical_url():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    url = "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/item-275791517?utm_source=test#section"
    canonical = adapter.canonicalize_url(url)
    assert "?" not in canonical
    assert "#" not in canonical
    assert not canonical.endswith("/")
    assert canonical == "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/item-275791517"


def test_extract_external_id_item_format():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    url = "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/apartament-2-camere-item-275791517"
    assert adapter.extract_external_id(url) == "275791517"


def test_extract_external_id_alphanumeric_fallback():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    url = "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/centru/apartament-2-camere-ID12345678"
    assert adapter.extract_external_id(url) == "ID12345678"


def test_extract_external_id_none_for_empty():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    assert adapter.extract_external_id("") is None


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 2: iter_jsonld_nodes și is_listing_node
# ══════════════════════════════════════════════════════════════════════════════

def test_iter_jsonld_nodes_graph():
    """iter_jsonld_nodes extrage noduri din @graph."""
    from app.modules.scraping.adapters.imobiliare_ro import iter_jsonld_nodes
    soup = make_soup("result_page_jsonld.html")
    nodes = list(iter_jsonld_nodes(soup))
    assert len(nodes) >= 3  # CollectionPage + Person + 3 listing nodes


def test_iter_jsonld_nodes_invalid_ignored():
    """Bloc JSON invalid este ignorat; blocul valid următor este procesat."""
    from app.modules.scraping.adapters.imobiliare_ro import iter_jsonld_nodes
    soup = make_soup("jsonld_invalid.html")
    nodes = list(iter_jsonld_nodes(soup))
    assert len(nodes) == 1
    assert "777777777" in nodes[0].get("@id", "")


def test_iter_jsonld_nodes_list_format():
    """iter_jsonld_nodes acceptă și JSON ca listă (nu doar dict cu @graph)."""
    from app.modules.scraping.adapters.imobiliare_ro import iter_jsonld_nodes
    html = """<html><head></head><body>
    <script type="application/ld+json">[{"@id": "test1", "name": "A"}, {"@id": "test2", "name": "B"}]</script>
    </body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    nodes = list(iter_jsonld_nodes(soup))
    assert len(nodes) == 2


def test_is_listing_node_true_by_id():
    """Nod cu @id /schema/Product/item- → listing."""
    from app.modules.scraping.adapters.imobiliare_ro import is_listing_node
    node = {"@id": "https://www.imobiliare.ro/#/schema/Product/item-275791517"}
    assert is_listing_node(node) is True


def test_is_listing_node_true_by_signals():
    """Nod fără @id schema dar cu offers + description + name → listing."""
    from app.modules.scraping.adapters.imobiliare_ro import is_listing_node
    node = {
        "name": "Apartament 2 camere",
        "description": "Desc",
        "address": {"@type": "PostalAddress"},
        "offers": {"priceSpecification": {"price": 50000, "priceCurrency": "EUR"}},
    }
    assert is_listing_node(node) is True


def test_is_listing_node_ignores_person():
    """Nod de tip Person → nu este listing."""
    from app.modules.scraping.adapters.imobiliare_ro import is_listing_node
    assert is_listing_node({"@type": "Person", "name": "Ion"}) is False


def test_is_listing_node_ignores_webpage():
    """Nod de tip WebPage → nu este listing."""
    from app.modules.scraping.adapters.imobiliare_ro import is_listing_node
    assert is_listing_node({
        "@type": "WebPage",
        "@id": "https://www.imobiliare.ro/vanzare-apartamente/judet-alba",
        "dateModified": "2026-08-04",
    }) is False


def test_is_listing_node_ignores_collection_page():
    from app.modules.scraping.adapters.imobiliare_ro import is_listing_node
    assert is_listing_node({"@type": "CollectionPage"}) is False


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 3: External ID și URL din JSON-LD
# ══════════════════════════════════════════════════════════════════════════════

def test_extract_external_id_from_node_id():
    """External ID extras din câmpul @id al nodului JSON-LD."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"@id": "https://www.imobiliare.ro/#/schema/Product/item-275791517"}
    assert adapter._extract_external_id_from_node(node) == "275791517"


def test_extract_external_id_from_sku():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"sku": "88776655"}
    assert adapter._extract_external_id_from_node(node) == "88776655"


def test_extract_external_id_from_node_missing():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    assert adapter._extract_external_id_from_node({}) is None


def test_extract_listing_url_from_html():
    """extract_listing_url găsește URL-ul din HTML când JSON-LD nu îl conține."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"@id": "https://www.imobiliare.ro/#/schema/Product/item-111111111"}
    soup = make_soup("result_page_jsonld.html")
    url = adapter.extract_listing_url(node, soup, "111111111")
    assert url is not None
    assert "item-111111111" in url
    assert "?" not in url  # canonicalizat


def test_extract_listing_url_from_node_url_field():
    """extract_listing_url returnează node.url direct dacă e navigabil."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"url": "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/item-999888777"}
    url = adapter.extract_listing_url(node)
    assert url == "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/item-999888777"


def test_extract_listing_url_missing():
    """extract_listing_url returnează None când nu există URL navigabil."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"@id": "https://www.imobiliare.ro/#/schema/Product/item-000000000"}
    url = adapter.extract_listing_url(node, soup=None, external_id=None)
    assert url is None


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 4: Extractori JSON-LD
# ══════════════════════════════════════════════════════════════════════════════

def test_extract_jsonld_price_from_price_specification():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"offers": {"priceSpecification": {"price": 75000, "priceCurrency": "EUR"}}}
    assert adapter.extract_jsonld_price(node) == 75000.0


def test_extract_jsonld_price_from_offers_direct():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"offers": {"price": 50000}}
    assert adapter.extract_jsonld_price(node) == 50000.0


def test_extract_jsonld_price_missing():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    assert adapter.extract_jsonld_price({}) is None
    assert adapter.extract_jsonld_price({"offers": {}}) is None


def test_extract_jsonld_currency_eur():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"offers": {"priceSpecification": {"price": 75000, "priceCurrency": "EUR"}}}
    assert adapter.extract_jsonld_currency(node) == "EUR"


def test_extract_jsonld_currency_ron():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"offers": {"priceCurrency": "RON", "price": 300000}}
    assert adapter.extract_jsonld_currency(node) == "RON"


def test_extract_jsonld_description():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"description": "Apartament cu 2 camere."}
    assert adapter.extract_jsonld_description(node) == "Apartament cu 2 camere."


def test_extract_jsonld_images_mixed():
    """extract_jsonld_images acceptă string și ImageObject în aceeași listă."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {
        "image": [
            {"@type": "ImageObject", "url": "https://i.roamcdn.net/img/1.jpg"},
            "https://i.roamcdn.net/img/2.jpg",
        ]
    }
    images = adapter.extract_jsonld_images(node)
    assert len(images) == 2
    assert all(u.startswith("https://") for u in images)


def test_extract_jsonld_images_single_object():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"image": {"@type": "ImageObject", "contentUrl": "https://i.roamcdn.net/img/3.jpg"}}
    images = adapter.extract_jsonld_images(node)
    assert len(images) == 1


def test_extract_jsonld_locality_from_address():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"address": {"@type": "PostalAddress", "addressLocality": "Alba Iulia"}}
    assert adapter.extract_jsonld_locality(node) == "Alba Iulia"


def test_extract_jsonld_locality_missing():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    assert adapter.extract_jsonld_locality({}) is None


def test_extract_jsonld_updated_at():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    node = {"dateModified": "2026-08-01T12:00:00.000000Z"}
    dt = adapter.extract_jsonld_updated_at(node)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 8
    assert dt.day == 1


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 5: discover_listing_refs
# ══════════════════════════════════════════════════════════════════════════════

def test_discover_listing_refs_jsonld():
    """discover_listing_refs extrage 3 URL-uri din fixture-ul cu JSON-LD."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("result_page_jsonld.html")
    refs = adapter.discover_listing_refs(html)
    assert len(refs) == 3
    assert all("imobiliare.ro" in r for r in refs)
    assert all("item-" in r for r in refs)


def test_discover_listing_refs_deduplication():
    """Același item-ID apare de 2 ori în HTML — trebuie returnat o singură dată."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("result_page_jsonld.html")
    refs = adapter.discover_listing_refs(html)
    urls_set = set(refs)
    assert len(refs) == len(urls_set), "URL-uri duplicate în rezultat"


def test_discover_listing_refs_person_ignored():
    """Nodul Person din @graph nu generează URL de listing."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("result_page_jsonld.html")
    refs = adapter.discover_listing_refs(html)
    assert not any("Person" in r or "agent-999" in r for r in refs)


def test_discover_listing_refs_html_fallback():
    """Fallback HTML pentru pagina cu JSON-LD invalid dar cu linkuri item-."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("jsonld_invalid.html")
    refs = adapter.discover_listing_refs(html)
    # JSON-LD valid returnează 1 nod fără URL → HTML fallback preia linkul
    assert len(refs) >= 1
    assert any("777777777" in r for r in refs)


def test_discover_result_pages():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    pages = adapter.discover_result_pages("vanzare-apartamente/judet-alba", max_pages=3)
    assert len(pages) == 3
    assert "pagina=2" in pages[1]
    assert "pagina=3" in pages[2]


def test_extract_next_page_url_from_nav():
    """extract_next_page_url detectează pagina 2 din navigație."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    soup = make_soup("result_page_jsonld.html")
    next_url = adapter.extract_next_page_url(
        soup, "https://www.imobiliare.ro/vanzare-apartamente/judet-alba"
    )
    assert next_url is not None
    assert "pagina=2" in next_url


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 6: parse_listing din fixture-uri JSON-LD
# ══════════════════════════════════════════════════════════════════════════════

def test_published_at_parsed():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.published_at is not None
    assert listing.published_at.year == 2026
    assert listing.published_at.month == 7
    assert listing.published_at.day == 15


def test_seller_type_private():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_private.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-222222222"))
    assert listing is not None
    assert listing.seller_type == "private"
    assert listing.seller_name == "Maria Ionescu"
    assert listing.agency_name is None


def test_seller_type_agency():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.seller_type == "agency"
    assert listing.agency_name == "Imobiliare Test SRL"


def test_seller_type_developer():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_developer.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-333333333"))
    assert listing is not None
    assert listing.seller_type == "developer"


def test_locality_alba():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.location_raw == "Alba Iulia"


def test_zone_extracted():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.zone_raw == "Centru"


def test_price_eur():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.price_eur == 75000.0


def test_price_ron_conversion():
    """Listing cu preț RON → conversie EUR + warning după normalize."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_developer.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-333333333"))
    assert listing is not None
    assert listing.original_currency == "RON"
    assert listing.original_price == 300000.0
    normalized = adapter.normalize_listing(listing)
    assert normalized.price_eur is not None
    assert "pret_convertit_din_ron" in normalized.quality_warnings


def test_surfaces():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_developer.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-333333333"))
    assert listing is not None
    assert listing.surface_m2 == 120.0


def test_images_jsonld():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_jsonld.html")
    listing = adapter.parse_listing(raw(html))
    assert listing is not None
    assert listing.image_count == 2
    assert all(u.startswith("https://") for u in listing.image_urls)


def test_listing_no_price():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_no_price.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-444444444"))
    assert listing is not None
    normalized = adapter.normalize_listing(listing)
    assert normalized.price_eur is None
    assert "pret_lipsa" in normalized.quality_warnings
    assert normalized.data_quality == "warning"


def test_listing_no_locality():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("detail_page_no_locality.html")
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-555555555"))
    assert listing is not None
    normalized = adapter.normalize_listing(listing)
    assert normalized.location_raw is None
    assert "localitate_lipsa" in normalized.quality_warnings


def test_html_fallback_when_no_jsonld():
    """HTML fallback când pagina nu are JSON-LD de tip listing."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = "<html><body><h1>Apartament test</h1></body></html>"
    listing = adapter.parse_listing(raw(html, "https://www.imobiliare.ro/test/item-999888777"))
    assert listing is not None
    assert listing.title == "Apartament test"
    assert "html_fallback" in listing.quality_warnings


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 7: Block detection
# ══════════════════════════════════════════════════════════════════════════════

def test_challenge_detection():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    html = load_fixture("challenge_page.html")
    assert adapter.detect_block_page(html, 200) is True
    assert adapter.detect_block_page("", 403) is True
    assert adapter.detect_block_page("", 429) is True
    assert adapter.detect_block_page("<html><body>OK</body></html>" * 10, 200) is False


def test_blocked_on_403():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter, ImobiliareRoBlockedError
    adapter = ImobiliareRoAdapter()
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    with pytest.raises(ImobiliareRoBlockedError):
        adapter._fetch_with_retry(mock_client, "https://www.imobiliare.ro/test")


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 8: DB — Idempotență, PriceHistory, stări
# ══════════════════════════════════════════════════════════════════════════════

def test_idempotency(session, source):
    from app.modules.market.service import save_listing
    from app.modules.market.models import MarketListing

    kwargs = dict(
        source_id=source.id, city_id=None, external_id="IDTEST001",
        url="https://www.imobiliare.ro/test/item-IDTEST001",
        title="Test Apartament", description="Desc", price_eur=50000.0, currency="EUR",
        rooms=2, surface_m2=55.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type="private",
    )

    result1, listing1 = save_listing(session, **kwargs)
    assert result1 == "created"
    result2, listing2 = save_listing(session, **kwargs)
    assert result2 == "unchanged"
    assert listing1.id == listing2.id

    listings = session.exec(select(MarketListing).where(MarketListing.source_id == source.id)).all()
    assert len(listings) == 1


def test_price_history(session, source):
    from app.modules.market.service import save_listing
    from app.modules.market.models import PriceHistory

    kwargs = dict(
        source_id=source.id, city_id=None, external_id="IDPH001",
        url="https://www.imobiliare.ro/test/item-IDPH001",
        title="Test PH", description=None, price_eur=50000.0, currency="EUR",
        rooms=2, surface_m2=55.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None,
    )
    save_listing(session, **kwargs)
    save_listing(session, **{**kwargs, "price_eur": 48000.0})

    ph_list = session.exec(select(PriceHistory)).all()
    assert len(ph_list) >= 1
    assert ph_list[-1].price_eur == 48000.0


def test_latest_run_state_new(session, source):
    from app.modules.market.service import save_listing
    result, listing = save_listing(
        session, source_id=source.id, city_id=None, external_id="IDNEW001",
        url="https://www.imobiliare.ro/test/item-IDNEW001",
        title="New Listing", description=None, price_eur=60000.0, currency="EUR",
        rooms=2, surface_m2=50.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None, job_id=1,
    )
    assert result == "created"
    assert listing.latest_run_state == "new"
    assert listing.created_by_scrape_job_id == 1


def test_latest_run_state_modified(session, source):
    from app.modules.market.service import save_listing
    save_listing(
        session, source_id=source.id, city_id=None, external_id="IDMOD001",
        url="https://www.imobiliare.ro/test/item-IDMOD001",
        title="Listing Initial", description=None, price_eur=70000.0, currency="EUR",
        rooms=2, surface_m2=60.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None, job_id=1,
    )
    result, updated = save_listing(
        session, source_id=source.id, city_id=None, external_id="IDMOD001",
        url="https://www.imobiliare.ro/test/item-IDMOD001",
        title="Listing Modificat", description=None, price_eur=65000.0, currency="EUR",
        rooms=2, surface_m2=60.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None, job_id=2,
    )
    assert result == "updated"
    assert updated.latest_run_state == "modified"
    assert updated.last_changed_by_scrape_job_id == 2
    assert updated.last_changed_at is not None


def test_latest_run_state_unchanged(session, source):
    from app.modules.market.service import save_listing
    kwargs = dict(
        source_id=source.id, city_id=None, external_id="IDUNC001",
        url="https://www.imobiliare.ro/test/item-IDUNC001",
        title="Listing Unchanged", description=None, price_eur=80000.0, currency="EUR",
        rooms=3, surface_m2=75.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None,
    )
    save_listing(session, **kwargs)
    result, listing = save_listing(session, **kwargs)
    assert result == "unchanged"
    assert listing.latest_run_state == "unchanged"


def test_inactive_detection(session, source):
    from app.modules.market.service import save_listing, mark_inactive_listings
    _, listing = save_listing(
        session, source_id=source.id, city_id=None, external_id="IDINACT001",
        url="https://www.imobiliare.ro/test/item-IDINACT001",
        title="Inactive Test", description=None, price_eur=50000.0, currency="EUR",
        rooms=2, surface_m2=50.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None,
    )
    for _ in range(3):
        mark_inactive_listings(
            session, source_id=source.id,
            seen_external_ids=set(), seen_urls=set(), threshold=3,
        )
        session.refresh(listing)
    assert listing.missing_count >= 3
    assert listing.listing_status == "inactive"


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 9: Orchestrator și scheduler
# ══════════════════════════════════════════════════════════════════════════════

def test_manual_job_trigger(engine):
    from app.modules.market.models import Source
    from app.modules.scraping.models import ScrapeJob
    from app.modules.scraping.adapters.base import ScrapedListing

    with Session(engine) as session:
        src = Source(name="Imobiliare.ro", slug="imobiliare_ro", base_url="https://www.imobiliare.ro", is_active=True)
        session.add(src)
        session.commit()

    mock_listing = ScrapedListing(
        title="Test", url="https://www.imobiliare.ro/test/item-IDJOB001",
        description=None, price_eur=50000.0, rooms=2, surface_m2=50.0,
        location_raw="Alba Iulia", image_urls=[],
        external_id="IDJOB001", property_type="apartment", transaction_type="sale",
        seller_type="private",
    )

    # Orchestratorul consumă adapter.iter_batches() (salvare pe loturi)
    with patch(
        "app.modules.scraping.adapters.imobiliare_ro.ImobiliareRoAdapter.iter_batches",
        return_value=iter([[mock_listing]])
    ), patch("app.modules.scraping.orchestrator.engine", engine), \
       patch("app.core.config.settings.scrape_imobiliare_ro_enabled", True), \
       patch("app.core.config.settings.scrape_imobiliare_ro_authorized", True):

        from app.modules.scraping.orchestrator import _run_scrape_job_sync

        with Session(engine) as session:
            job = ScrapeJob(source_name="imobiliare_ro", trigger_type="manual",
                            status="queued", queued_at=datetime.utcnow())
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

        _run_scrape_job_sync(job_id)

        with Session(engine) as session:
            job = session.get(ScrapeJob, job_id)
            assert job.status == "completed"
            assert job.listings_created >= 1


def test_scheduled_job_skips_if_active(engine):
    import asyncio
    from app.modules.market.models import Source
    from app.modules.scraping.models import ScrapeJob

    with Session(engine) as session:
        src = Source(name="Imobiliare.ro", slug="imobiliare_ro", base_url="https://www.imobiliare.ro", is_active=True)
        session.add(src)
        active_job = ScrapeJob(source_name="imobiliare_ro", trigger_type="manual",
                               status="running", queued_at=datetime.utcnow())
        session.add(active_job)
        session.commit()

    with patch("app.database.session.engine", engine):
        from app.modules.scraping.scheduler import _scheduled_scrape
        asyncio.get_event_loop().run_until_complete(_scheduled_scrape("imobiliare_ro"))

    with Session(engine) as session:
        jobs = session.exec(select(ScrapeJob).where(ScrapeJob.source_name == "imobiliare_ro")).all()
        assert len(jobs) == 1


def test_source_all_includes_imobiliare_ro():
    from app.modules.scraping.registry import list_source_keys
    keys = list_source_keys()
    assert "publi24" in keys
    assert "imobiliare_ro" in keys


def test_source_isolation(session):
    from app.modules.market.models import Source, MarketListing
    from app.modules.market.service import save_listing

    src1 = Source(name="Publi24", slug="publi24", base_url="https://www.publi24.ro", is_active=True)
    src2 = Source(name="Imobiliare.ro", slug="imobiliare_ro", base_url="https://www.imobiliare.ro", is_active=True)
    session.add(src1)
    session.add(src2)
    session.commit()
    session.refresh(src1)
    session.refresh(src2)

    common = dict(
        city_id=None, external_id="SAME_ID",
        title="Test", description=None, price_eur=50000.0, currency="EUR",
        rooms=2, surface_m2=50.0, property_type="apartment", transaction_type="sale",
        location_raw="Alba Iulia", published_at=None, zone_raw=None,
        zone_normalized=None, seller_type=None,
    )
    save_listing(session, source_id=src1.id, url="https://www.publi24.ro/test/SAME_ID", **common)
    save_listing(session, source_id=src2.id, url="https://www.imobiliare.ro/test/SAME_ID", **common)

    p24 = session.exec(select(MarketListing).where(MarketListing.source_id == src1.id)).all()
    imob = session.exec(select(MarketListing).where(MarketListing.source_id == src2.id)).all()
    assert len(p24) == 1
    assert len(imob) == 1


def test_imobiliare_failure_doesnt_stop_publi24(engine):
    from app.modules.market.models import Source
    from app.modules.scraping.models import ScrapeJob
    from app.modules.scraping.adapters.base import ScrapedListing

    with Session(engine) as session:
        src1 = Source(name="Publi24", slug="publi24", base_url="https://www.publi24.ro", is_active=True)
        src2 = Source(name="Imobiliare.ro", slug="imobiliare_ro", base_url="https://www.imobiliare.ro", is_active=True)
        session.add(src1)
        session.add(src2)
        session.commit()

    mock_publi24_listing = ScrapedListing(
        title="Publi24 Test", url="https://www.publi24.ro/test/P001",
        description=None, price_eur=40000.0, rooms=2, surface_m2=45.0,
        location_raw="Alba Iulia", image_urls=[],
    )

    def run_job(source_name, s):
        job = ScrapeJob(source_name=source_name, trigger_type="manual",
                        status="queued", queued_at=datetime.utcnow())
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id

    with patch("app.modules.scraping.orchestrator.engine", engine):
        from app.modules.scraping.orchestrator import _run_scrape_job_sync

        with patch("app.modules.scraping.adapters.imobiliare_ro.ImobiliareRoAdapter.iter_batches", side_effect=RuntimeError("Blocat")):
            with Session(engine) as s:
                imob_job_id = run_job("imobiliare_ro", s)
            _run_scrape_job_sync(imob_job_id)

        with patch("app.modules.scraping.adapters.publi24.Publi24Adapter.iter_batches", return_value=iter([[mock_publi24_listing]])):
            with Session(engine) as s:
                p24_job_id = run_job("publi24", s)
            _run_scrape_job_sync(p24_job_id)

    with Session(engine) as s:
        imob_job = s.get(ScrapeJob, imob_job_id)
        p24_job = s.get(ScrapeJob, p24_job_id)
        assert imob_job.status == "failed"
        assert p24_job.status == "completed"


def test_max_one_active_job_per_source(engine):
    from app.modules.market.models import Source
    from app.modules.scraping.models import ScrapeJob

    with Session(engine) as session:
        src = Source(name="Imobiliare.ro", slug="imobiliare_ro", base_url="https://www.imobiliare.ro", is_active=True)
        session.add(src)
        session.commit()

    with Session(engine) as session:
        job1 = ScrapeJob(source_name="imobiliare_ro", trigger_type="manual",
                         status="running", queued_at=datetime.utcnow())
        session.add(job1)
        session.commit()

        from app.modules.scraping.orchestrator import ACTIVE_STATUSES
        active = session.exec(
            select(ScrapeJob)
            .where(ScrapeJob.source_name == "imobiliare_ro")
            .where(ScrapeJob.status.in_(list(ACTIVE_STATUSES)))
        ).first()
        assert active is not None
        assert active.id == job1.id


# ══════════════════════════════════════════════════════════════════════════════
# SECȚIUNEA 10: Frontend și TypeScript
# ══════════════════════════════════════════════════════════════════════════════

def test_frontend_source_filter_options():
    frontend_path = Path("/sessions/ecstatic-busy-newton/mnt/scraper-digitalizare/frontend/app/(dashboard)/listings/page.tsx")
    if frontend_path.exists():
        content = frontend_path.read_text()
        assert "filterSource" in content or "SOURCE_OPTIONS" in content or "source_slug" in content


def test_frontend_scraping_panel_exists():
    frontend_path = Path("/sessions/ecstatic-busy-newton/mnt/scraper-digitalizare/frontend/app/(dashboard)/listings/page.tsx")
    if frontend_path.exists():
        content = frontend_path.read_text()
        assert "ScrapingPanel" in content
        assert "imobiliare_ro" in content or "Imobiliare" in content


def test_typescript_types():
    types_path = Path("/sessions/ecstatic-busy-newton/mnt/scraper-digitalizare/frontend/lib/types.ts")
    if types_path.exists():
        content = types_path.read_text()
        assert "seller_type" in content
        assert "latest_run_state" in content or "listing_status" in content
