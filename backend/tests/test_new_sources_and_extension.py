"""
Teste pentru: Publi24 (listare rapidă din carduri), OLX (API), imobiliare.ro
(JSON din pagina de rezultate), salvarea pe loturi, filtrele noi și API-ul extensiei.
Fără rețea — fixture-urile reproduc structura reală a site-urilor (sept. 2026).
"""
import html as htmllib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


# ── Publi24 ───────────────────────────────────────────────────────────────────

PUBLI24_HTML = """
<div class="article-item article-item-b2b-phone" data-articleid="C2D2">
  <div class="art-img"><a href="https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/apartamente-2-camere/anunt/apartament-2-camere-etaj-2-cugir/f5g5e0h7d5ii708926ddg14e162eiidi.html">
    <img src="https://s3.publi24.ro/vertical/top/1.webp"></a></div>
  <h2 class="article-title"><a href="https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/apartamente-2-camere/anunt/apartament-2-camere-etaj-2-cugir/f5g5e0h7d5ii708926ddg14e162eiidi.html">Apartament 2 camere, etaj 2 - Cugir</a></h2>
  <p class="article-description">Suprafata utila de 45 mp.</p>
  <p class="article-short-info"><span class="article-lbl-txt">800 EUR/m<sup>2</sup> | 45 m<sup>2</sup></span></p>
  <p class="article-location"><span>central, Cugir, Alba</span></p>
  <p class="article-date">ieri 18:24</p>
  <span class="article-price"><span class="new-price">36,000 EUR</span><span class="old-price">37,000 EUR</span></span>
</div>
<div class="article-item" data-articleid="X1">
  <h2 class="article-title"><a href="/anunturi/imobiliare/de-vanzare/apartamente/garsoniere/anunt/garsoniera-cetate/abc123.html">Garsoniera Cetate proprietar</a></h2>
  <p class="article-short-info"><span>30 m2</span></p>
  <p class="article-location"><span>Cetate, Alba Iulia, Alba</span></p>
  <p class="article-date">11 septembrie</p>
  <span class="article-price">42 000 EUR</span>
</div>
<div class="article-item" data-articleid="X2">
  <h2 class="article-title"><a href="/anunturi/imobiliare/de-vanzare/terenuri/anunt/teren/zzz.html">Teren Tartasesti</a></h2>
  <p class="article-location"><span>Tartasesti, Dambovita</span></p>
  <span class="article-price">100 000 EUR</span>
</div>
<a href="/anunturi/imobiliare/de-vanzare/apartamente/alba/?pag=2">2</a>
"""


def test_publi24_list_page_seller_and_county():
    from app.modules.scraping.publi24.scraper import parse_list_page

    listings, has_next = parse_list_page(PUBLI24_HTML, "apartment", "sale")
    assert has_next
    assert len(listings) == 2  # Dâmbovița e exclus
    a, b = listings
    assert a.seller_type == "agency" and b.seller_type == "private"
    assert a.price_eur == 36000 and a.surface_m2 == 45 and a.rooms == 2
    assert a.location_raw == "Cugir" and a.zone_raw == "central"
    assert a.external_id == "f5g5e0h7d5ii708926ddg14e162eiidi"
    assert b.location_raw == "Alba Iulia" and b.rooms == 1 and b.price_eur == 42000
    assert b.published_at is not None and b.published_at.day == 11


# ── OLX ───────────────────────────────────────────────────────────────────────

def test_olx_map_offer():
    from app.modules.scraping.adapters.olx import map_offer

    offer = {
        "id": 308397683,
        "url": "https://www.olx.ro/d/oferta/casa-de-vanzare-hula-IDkS0kb.html?reason=x",
        "title": "Casa de vanzare - Str. Petru Maior (Hula)",
        "created_time": "2026-08-22T10:34:29+03:00",
        "description": "Suprafață teren: 640 m²<br />",
        "params": [
            {"key": "rooms", "value": {"key": "three", "label": "3 camere"}},
            {"key": "price", "value": {"value": 170000, "currency": "EUR", "label": "170 000 €"}},
            {"key": "m", "value": {"key": "130", "label": "130 m²"}},
        ],
        "business": False,
        "user": {"name": "mircea"},
        "location": {"city": {"name": "Blaj"}, "region": {"id": 28, "name": "Alba"}},
        "photos": [{"link": "https://x/image;s={width}x{height}"}],
        "category": {"id": 911},
    }
    l = map_offer(offer, "house", "sale")
    assert l.seller_type == "private" and l.price_eur == 170000 and l.surface_m2 == 130
    assert l.rooms == 3 and l.location_raw == "Blaj" and l.external_id == "308397683"
    assert l.url.endswith("IDkS0kb.html") and l.image_urls == ["https://x/image;s=800x600"]

    land = map_offer({
        "id": 1, "url": "u", "title": "Teren intravilan Barabant",
        "params": [{"key": "price", "value": {"value": 55, "currency": "EUR"}},
                   {"key": "m", "value": {"key": "510"}}],
        "business": True, "location": {"region": {"id": 28}},
    }, "land", "sale")
    assert land.price_eur == 28050 and land.seller_type == "agency"

    rent_space = {"id": 2, "url": "u2", "title": "Spatiu", "location": {"region": {"id": 28}},
                  "params": [{"key": "alege", "value": {"key": "inchiriere"}}]}
    assert map_offer(rent_space, "commercial", "sale") is None
    assert map_offer(rent_space, "commercial", "rent").transaction_type == "rent"
    assert map_offer({"id": 3, "url": "u3", "title": "x", "params": [],
                      "location": {"region": {"id": 18}}}, "house", "sale") is None


# ── imobiliare.ro ─────────────────────────────────────────────────────────────

def test_imobiliare_result_page_json():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter

    page = {"component": "Search/Index", "props": {"searchMeta": {"lastPage": 37}, "sections": [
        {"type": "results-list", "data": {"listings": [{
            "id": 275829355,
            "url": "/oferta/apartament-de-vanzare-sebes-kogalniceanu-2-camere-275829355",
            "title": "Apartament cu 2 camere de vânzare",
            "location": "Kogălniceanu, Sebeș",
            "price": "52.000 €",
            "images": [{"src": "https://i.roamcdn.net/x.jpg"}],
            "highlights": [{"key": "bedroom_count", "label": "2 camere"},
                           {"key": "usable_surface", "label": "57 mp"},
                           {"key": "year_built", "label": "1988"}],
            "agencyName": "REMAX Sky",
            "tracking": {"ga4Item": {"price": 52000, "sellerType": "agency"}},
        }]}},
    ]}}
    html = f'<div id="app" data-page="{htmllib.escape(json.dumps(page))}"></div>'
    listings, last = ImobiliareRoAdapter().listings_from_result_page(html, "apartment", "sale")
    assert last == 37
    (l,) = listings
    assert l.price_eur == 52000 and l.surface_m2 == 57 and l.rooms == 2 and l.construction_year == 1988
    assert l.location_raw == "Sebeș" and l.zone_raw == "Kogălniceanu" and l.seller_type == "agency"
    assert l.url.startswith("https://www.imobiliare.ro/oferta/")
    assert ImobiliareRoAdapter().listings_from_result_page("<html></html>", "apartment", "sale") is None


# ── Salvare pe loturi + filtre + extensie ─────────────────────────────────────

def _seed(engine):
    from app.modules.market.models import City, Source
    from app.modules.scraping.adapters.base import ScrapedListing
    from app.modules.scraping.orchestrator import _import_listings

    with Session(engine) as s:
        s.add(City(name="Alba Iulia", county="Alba"))
        s.add(City(name="Sebeș", county="Alba"))
        s.add(Source(name="OLX", slug="olx", base_url="https://www.olx.ro", is_active=True))
        s.add(Source(name="Storia", slug="storia", base_url="https://www.storia.ro", is_active=True))
        s.commit()
        olx = s.exec(select(Source).where(Source.slug == "olx")).one()
        storia = s.exec(select(Source).where(Source.slug == "storia")).one()

        def mk(i, **kw):
            base = dict(title=f"Apartament 2 camere {i}", url=f"https://www.olx.ro/d/oferta/ap-ID{i}.html",
                        description=None, price_eur=80000.0, rooms=2, surface_m2=50.0,
                        location_raw="Alba Iulia", image_urls=[], external_id=f"{i}",
                        property_type="apartment", transaction_type="sale", seller_type="private")
            base.update(kw)
            return ScrapedListing(**base)

        olx_batch = [
            mk(1),
            mk(2, price_eur=60000.0, seller_type="agency"),
            mk(3, price_eur=70000.0),
            mk(4, price_eur=100000.0),
            mk(5, title="Casa Sebes", property_type="house", location_raw="Sebeș", surface_m2=120.0, rooms=4),
            mk(6, title="Teren", property_type="land", rooms=None, surface_m2=600.0, price_eur=30000.0),
        ]
        _import_listings(s, olx_batch, olx.id, "olx")
        # același apartament ca #1, pe Storia, puțin mai ieftin
        _import_listings(s, [mk(99, url="https://www.storia.ro/ro/oferta/ap-99", price_eur=79000.0,
                                seller_type="agency")], storia.id, "storia")


def test_orchestrator_saves_batches(engine):
    from app.modules.market.models import MarketListing, Source
    from app.modules.scraping.adapters.base import ScrapedListing
    from app.modules.scraping.models import ScrapeJob
    from app.modules.scraping.orchestrator import _run_scrape_job_sync

    with Session(engine) as s:
        s.add(Source(name="OLX", slug="olx", base_url="https://www.olx.ro", is_active=True))
        job = ScrapeJob(source_name="olx", status="queued", queued_at=datetime.utcnow())
        s.add(job)
        s.commit()
        job_id = job.id

    def batches(self, max_pages=25):
        for n in range(3):
            yield [ScrapedListing(title=f"T{n}", url=f"https://www.olx.ro/d/oferta/x-ID{n}.html", description=None,
                                  price_eur=1.0, rooms=1, surface_m2=1.0, location_raw="Alba", image_urls=[],
                                  external_id=str(n), property_type="apartment", transaction_type="sale")]

    with patch("app.modules.scraping.orchestrator.engine", engine), \
         patch("app.modules.scraping.adapters.olx.OlxAdapter.iter_batches", batches):
        _run_scrape_job_sync(job_id)

    with Session(engine) as s:
        job = s.get(ScrapeJob, job_id)
        assert job.status == "completed"
        assert job.listings_found == 3 and job.pages_processed == 3 and job.listings_created == 3
        assert len(s.exec(select(MarketListing)).all()) == 3


@pytest.fixture(name="client")
def client_fixture(engine):
    from app.main import app
    from app.database.session import get_session
    from app.modules.auth.dependencies import get_current_user

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_current_user] = lambda: object()
    with patch("app.modules.scraping.scheduler.setup_scheduler"), \
         patch("app.modules.scraping.orchestrator.recover_stuck_jobs"), \
         patch("app.core.config.settings.extension_api_key", "cheie-test"):
        yield TestClient(app)
    app.dependency_overrides.clear()


def test_listing_filters_and_summary(engine, client):
    _seed(engine)
    r = client.get("/api/v1/market/listings", params={"property_type": "apartment", "seller_type": "private"})
    assert r.status_code == 200
    assert {l["title"] for l in r.json()} == {"Apartament 2 camere 1", "Apartament 2 camere 3", "Apartament 2 camere 4"}

    r = client.get("/api/v1/market/listings", params={"property_type": "house,land"})
    assert len(r.json()) == 2

    r = client.get("/api/v1/market/listings", params={"q": "casa", "locality": "Sebe"})
    assert [l["title"] for l in r.json()] == ["Casa Sebes"]

    s = client.get("/api/v1/market/listings/summary", params={"property_type": "apartment"}).json()
    assert s["total"] == 5 and s["new_7d"] == 5
    assert s["by_seller_type"] == {"private": 3, "agency": 2}


def test_extension_auth_and_analyze(engine, client):
    _seed(engine)
    assert client.get("/api/v1/extension/ping").status_code == 401
    h = {"X-Extension-Key": "cheie-test"}
    assert client.get("/api/v1/extension/ping", headers=h).json()["listings"] == 7

    # Anunț cunoscut (OLX #1 = 80.000 €, 50 mp)
    r = client.post("/api/v1/extension/analyze", headers=h,
                    json={"url": "https://www.olx.ro/d/oferta/ap-ID1.html?reason=search"})
    d = r.json()
    assert d["known"]["id"]
    assert d["market"]["median_price_per_m2"] > 0
    assert [x["source"] for x in d["duplicates"]] == ["Storia"]
    alt = [x["price_eur"] for x in d["alternatives"]]
    assert alt and alt[0] == 70000  # proprietarii primii, apoi mai ieftin
    assert 60000 in alt

    # Anunț necunoscut: datele vin din pagină (extensie)
    r = client.post("/api/v1/extension/analyze", headers=h, json={
        "url": "https://www.imobiliare.ro/oferta/apartament-de-vanzare-alba-iulia-2-camere-1",
        "title": "Apartament 2 camere", "price_eur": 110000, "surface_m2": 50, "rooms": 2,
        "locality": "Alba Iulia",
    })
    d = r.json()
    assert d["known"] is None
    assert d["detected"]["property_type"] == "apartment" and d["detected"]["city"] == "Alba Iulia"
    assert d["market"]["verdict"] == "above" and d["market"]["diff_percent"] > 0

    r = client.get("/api/v1/extension/search", headers=h,
                   params={"property_type": "apartment", "seller_type": "private", "sort": "price_asc"})
    assert [x["price_eur"] for x in r.json()] == [70000, 80000, 100000]


def test_listings_pagination_and_server_sort(engine, client):
    _seed(engine)
    r = client.get("/api/v1/market/listings", params={"property_type": "apartment", "sort": "price_eur", "order": "asc", "limit": 2})
    assert [l["price_eur"] for l in r.json()] == [60000, 70000]
    r = client.get("/api/v1/market/listings", params={"property_type": "apartment", "sort": "price_eur", "order": "asc", "limit": 2, "offset": 2})
    assert [l["price_eur"] for l in r.json()] == [79000, 80000]
    r = client.get("/api/v1/market/listings", params={"property_type": "apartment", "sort": "price_eur", "order": "desc", "limit": 1})
    assert r.json()[0]["price_eur"] == 100000
