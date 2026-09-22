"""
API pentru extensia de browser (tip „Phia” pentru imobiliare).

Când ești pe un anunț (OLX, Storia, imobiliare.ro, Publi24, Romimo, HomeZZ),
extensia trimite datele anunțului aici și primește înapoi:
  - dacă anunțul e deja în baza ta (și de când, istoric preț)
  - prețul/m² comparat cu media pieței (aceeași localitate + același tip)
  - același imobil publicat pe alte site-uri (duplicat, eventual mai ieftin)
  - alternative similare mai ieftine, cu proprietarii primii

Autentificare: header `X-Extension-Key` = EXTENSION_API_KEY din backend/.env
(separat de login-ul aplicației, ca să nu te delogheze din dashboard —
aplicația permite o singură sesiune activă).
"""
import re
import statistics
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.database.session import get_session
from app.modules.market.models import City, MarketListing, MarketListingRaw, PriceHistory, Source
from app.modules.market.service import get_city_id_by_name

router = APIRouter(prefix="/extension", tags=["extension"])


def require_extension_key(x_extension_key: str | None = Header(default=None)) -> None:
    expected = settings.extension_api_key
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Extensia nu e configurată: pune EXTENSION_API_KEY în backend/.env și repornește backend-ul.",
        )
    if x_extension_key != expected:
        raise HTTPException(status_code=401, detail="Cheie extensie invalidă. Verifică setările extensiei.")


# ── Utilitare ──────────────────────────────────────────────────────────────────

def _fold(text: str | None) -> str:
    s = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def canonical_url(url: str) -> str:
    return (url or "").split("#")[0].split("?")[0].rstrip("/")


def guess_property_type(text: str) -> str | None:
    t = _fold(text)
    if re.search(r"apartament|garsonier|penthouse", t):
        return "apartment"
    if re.search(r"spatiu[ -]comercial|spatii[ -]comerciale|birou|hala|depozit|spatiu-industrial", t):
        return "commercial"
    if re.search(r"\b(casa|case|vila|vile|duplex|cabana)\b|case-|casa-|vila-", t):
        return "house"
    if re.search(r"\bteren|terenuri|parcela|intravilan|extravilan", t):
        return "land"
    return None


def guess_transaction(text: str) -> str:
    t = _fold(text)
    return "rent" if re.search(r"inchiri|chirie|de-inchiriat|/rent|inchiriere", t) else "sale"


SOURCE_BY_HOST = {
    "olx.ro": "olx",
    "storia.ro": "storia",
    "imobiliare.ro": "imobiliare_ro",
    "publi24.ro": "publi24",
    "romimo.ro": "romimo",
}


def _source_names(session: Session) -> dict[int, str]:
    return {s.id: s.name for s in session.exec(select(Source)).all()}


def _city_names(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.name for c in session.exec(select(City).where(City.id.in_(ids))).all()}


def _listing_out(l: MarketListing, sources: dict[int, str], cities: dict[int, str], images: dict[int, list]) -> dict:
    return {
        "id": l.id,
        "url": l.url,
        "title": l.title,
        "price_eur": l.price_eur,
        "surface_m2": l.surface_m2,
        "rooms": l.rooms,
        "price_per_m2": round(l.price_per_m2) if l.price_per_m2 else None,
        "property_type": l.property_type,
        "transaction_type": l.transaction_type,
        "seller_type": l.seller_type,
        "city": cities.get(l.city_id) if l.city_id else None,
        "zone": l.zone_normalized or l.zone_raw,
        "source": sources.get(l.source_id, ""),
        "first_seen_at": l.first_seen_at,
        "image": (images.get(l.raw_listing_id) or [None])[0],
    }


def _images_for(session: Session, listings: list[MarketListing]) -> dict[int, list]:
    ids = [l.raw_listing_id for l in listings]
    if not ids:
        return {}
    raws = session.exec(select(MarketListingRaw).where(MarketListingRaw.id.in_(ids))).all()
    return {r.id: (r.raw_payload or {}).get("image_urls", []) for r in raws}


def _active():
    return (
        select(MarketListing)
        .where(MarketListing.is_active == True)  # noqa: E712
        .where(MarketListing.listing_status != "inactive")
    )


# ── Endpoint-uri ──────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url: str
    title: str | None = None
    price_eur: float | None = None
    surface_m2: float | None = None
    rooms: int | None = None
    property_type: str | None = None      # apartment / house / land / commercial
    transaction_type: str | None = None   # sale / rent
    locality: str | None = None
    seller_type: str | None = None


@router.get("/ping", dependencies=[Depends(require_extension_key)])
def ping(session: Session = Depends(get_session)):
    from sqlalchemy import func
    total = session.exec(select(func.count(MarketListing.id)).where(MarketListing.is_active == True)).one()  # noqa: E712
    return {"ok": True, "listings": int(total or 0)}


@router.post("/analyze", dependencies=[Depends(require_extension_key)])
def analyze(body: AnalyzeRequest, session: Session = Depends(get_session)):
    url = canonical_url(body.url)
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
    sources = _source_names(session)

    # 1. Anunțul e deja în baza noastră?
    known = session.exec(select(MarketListing).where(MarketListing.url.in_([url, url + "/", body.url]))).first()
    if known is None and host == "olx.ro":
        m = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
        if m:
            raw = session.exec(select(MarketListingRaw).where(MarketListingRaw.external_id == m.group(1))).first()
            if raw:
                known = session.exec(select(MarketListing).where(MarketListing.raw_listing_id == raw.id)).first()

    text = f"{url} {body.title or ''}"
    ptype = (known.property_type if known else None) or body.property_type or guess_property_type(text)
    tx = (known.transaction_type if known else None) or body.transaction_type or guess_transaction(url)
    price = (known.price_eur if known and known.price_eur else None) or body.price_eur
    surface = (known.surface_m2 if known and known.surface_m2 else None) or body.surface_m2
    rooms = (known.rooms if known else None) or body.rooms
    city_id = known.city_id if known and known.city_id else (
        get_city_id_by_name(session, body.locality, county="Alba") if body.locality else None
    )
    ppm = round(price / surface) if price and surface else None

    # 2. Comparația cu piața (aceeași localitate + același tip + aceeași tranzacție)
    market = None
    if ptype:
        q = _active().where(MarketListing.property_type == ptype).where(MarketListing.transaction_type == tx)
        if city_id:
            q = q.where(MarketListing.city_id == city_id)
        if ptype == "apartment" and rooms:
            q = q.where(MarketListing.rooms == rooms) if rooms < 4 else q.where(MarketListing.rooms >= 4)
        peers = [l for l in session.exec(q.limit(3000)).all() if not known or l.id != known.id]
        ppms = [l.price_per_m2 for l in peers if l.price_per_m2 and 10 < l.price_per_m2 < 20000]
        prices = [l.price_eur for l in peers if l.price_eur]
        if len(ppms) >= 3 or len(prices) >= 3:
            median_ppm = round(statistics.median(ppms)) if len(ppms) >= 3 else None
            diff = round((ppm - median_ppm) / median_ppm * 100) if ppm and median_ppm else None
            if diff is None:
                verdict = "unknown"
            elif diff <= -10:
                verdict = "below"
            elif diff >= 10:
                verdict = "above"
            else:
                verdict = "fair"
            market = {
                "sample_size": len(peers),
                "median_price_eur": round(statistics.median(prices)) if prices else None,
                "median_price_per_m2": median_ppm,
                "diff_percent": diff,
                "verdict": verdict,
                "scope": "localitate" if city_id else "județul Alba",
            }

    # 3. Același imobil pe alte site-uri
    duplicates: list[MarketListing] = []
    if ptype and price and surface:
        q = (
            _active()
            .where(MarketListing.property_type == ptype)
            .where(MarketListing.transaction_type == tx)
            .where(MarketListing.price_eur.between(price * 0.95, price * 1.05))
            .where(MarketListing.surface_m2.between(surface - max(3, surface * 0.03), surface + max(3, surface * 0.03)))
        )
        if city_id:
            q = q.where(MarketListing.city_id == city_id)
        duplicates = [
            l for l in session.exec(q.limit(20)).all()
            if (not known or l.id != known.id) and canonical_url(l.url) != url
            and (rooms is None or l.rooms is None or l.rooms == rooms)
        ][:6]

    # 4. Alternative mai ieftine, similare — proprietarii primii
    alternatives: list[MarketListing] = []
    if ptype:
        q = _active().where(MarketListing.property_type == ptype).where(MarketListing.transaction_type == tx)
        if city_id:
            q = q.where(MarketListing.city_id == city_id)
        if surface:
            q = q.where(MarketListing.surface_m2.between(surface * 0.75, surface * 1.3))
        if ptype == "apartment" and rooms:
            q = q.where(MarketListing.rooms == rooms) if rooms < 4 else q.where(MarketListing.rooms >= 4)
        if ppm:
            q = q.where(MarketListing.price_per_m2 < ppm)
        elif price:
            q = q.where(MarketListing.price_eur < price)
        dup_ids = {d.id for d in duplicates}
        cands = [
            l for l in session.exec(q.order_by(MarketListing.price_per_m2.asc()).limit(60)).all()
            if (not known or l.id != known.id) and l.id not in dup_ids and canonical_url(l.url) != url
        ]
        cands.sort(key=lambda l: (0 if l.seller_type == "private" else 1, l.price_per_m2 or 1e9))
        alternatives = cands[:6]

    # 5. Istoric preț
    history = []
    if known:
        history = [
            {"price_eur": h.price_eur, "recorded_at": h.recorded_at}
            for h in session.exec(
                select(PriceHistory).where(PriceHistory.listing_id == known.id).order_by(PriceHistory.recorded_at)
            ).all()
        ]

    all_rows = ([known] if known else []) + duplicates + alternatives
    images = _images_for(session, all_rows)
    cities = _city_names(session, {l.city_id for l in all_rows if l.city_id} | ({city_id} if city_id else set()))

    return {
        "known": _listing_out(known, sources, cities, images) if known else None,
        "detected": {
            "property_type": ptype,
            "transaction_type": tx,
            "price_eur": price,
            "surface_m2": surface,
            "rooms": rooms,
            "price_per_m2": ppm,
            "city": cities.get(city_id) if city_id else body.locality,
            "source": SOURCE_BY_HOST.get(host),
            "seller_type": (known.seller_type if known else None) or body.seller_type,
        },
        "market": market,
        "duplicates": [_listing_out(l, sources, cities, images) for l in duplicates],
        "alternatives": [_listing_out(l, sources, cities, images) for l in alternatives],
        "price_history": history,
        "days_on_market": (datetime.utcnow() - known.first_seen_at).days if known else None,
    }


@router.get("/search", dependencies=[Depends(require_extension_key)])
def search(
    property_type: str | None = None,
    transaction_type: str | None = "sale",
    seller_type: str | None = None,
    locality: str | None = None,
    rooms: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_surface: float | None = None,
    q: str | None = None,
    new_days: int | None = None,
    sort: str = "new",
    limit: int = 40,
    session: Session = Depends(get_session),
):
    """Căutare rapidă din popup-ul extensiei."""
    from app.modules.market.router import _apply_listing_filters

    query = _apply_listing_filters(
        _active(), session,
        property_type=property_type, transaction_type=transaction_type, seller_type=seller_type,
        locality=locality, rooms=rooms, min_price=min_price, max_price=max_price,
        min_surface=min_surface, q=q, new_days=new_days,
    )
    order = {
        "new": MarketListing.first_seen_at.desc(),
        "price_asc": MarketListing.price_eur.asc(),
        "ppm_asc": MarketListing.price_per_m2.asc(),
    }.get(sort, MarketListing.first_seen_at.desc())
    rows = session.exec(query.order_by(order).limit(max(1, min(limit, 100)))).all()
    sources = _source_names(session)
    images = _images_for(session, rows)
    cities = _city_names(session, {l.city_id for l in rows if l.city_id})
    return [_listing_out(l, sources, cities, images) for l in rows]
