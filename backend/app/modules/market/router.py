from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.market.models import City, MarketListing, MarketListingRaw, Source
from app.modules.market.schemas import CityCreate, MarketListingCreate
from app.modules.scraping.publi24.scraper import fetch_images_for_url
from app.modules.users.models import User

router = APIRouter(prefix="/market", tags=["market"])


# ── Helper ─────────────────────────────────────────────────────────────────────

def _listing_with_quality(
    listing: MarketListing,
    raw_payload: dict[str, Any],
    location_raw: str | None = None,
) -> dict[str, Any]:
    """Construiește dicționarul de răspuns incluzând calitatea și localizarea."""
    return {
        "id": listing.id,
        "source_id": listing.source_id,
        "city_id": listing.city_id,
        "url": listing.url,
        "title": listing.title,
        "description": listing.description,
        "price_eur": listing.price_eur,
        "currency": listing.currency,
        "rooms": listing.rooms,
        "surface_m2": listing.surface_m2,
        "price_per_m2": listing.price_per_m2,
        "property_type": listing.property_type,
        "transaction_type": listing.transaction_type,
        "is_active": listing.is_active,
        "published_at": listing.published_at,
        "first_seen_at": listing.first_seen_at,
        "last_seen_at": listing.last_seen_at,
        # Zone fields
        "zone_raw": listing.zone_raw,
        "zone_normalized": listing.zone_normalized,
        # Din raw_payload — fără migrație
        "data_quality": raw_payload.get("data_quality", "valid"),
        "quality_warnings": raw_payload.get("quality_warnings", []),
        "image_urls": raw_payload.get("image_urls", []),
        # Localitate exactă din sursa brută
        "location_raw": location_raw,
        # Câmpuri extinse
        "seller_type": listing.seller_type,
        "latest_run_state": listing.latest_run_state,
        "listing_status": listing.listing_status,
    }


# ── Endpoints publice (fără auth — necesare pentru scraper intern) ─────────────

@router.get("/sources")
def list_sources(session: Session = Depends(get_session)):
    return session.exec(select(Source).order_by(Source.name)).all()


@router.get("/cities")
def list_cities(session: Session = Depends(get_session)):
    return session.exec(select(City).order_by(City.name)).all()


@router.post("/cities")
def get_or_create_city(city_data: CityCreate, session: Session = Depends(get_session)):
    """Returnează city existentă sau o creează dacă nu există (folosit de scraper)."""
    existing = session.exec(
        select(City).where(City.name == city_data.name)
    ).first()
    if existing:
        return existing
    city = City(name=city_data.name, county=city_data.county)
    session.add(city)
    session.commit()
    session.refresh(city)
    return city


@router.get("/zones")
def list_zones(
    city_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Returns list of distinct non-null zone_normalized values, optionally filtered by city."""
    query = (
        select(MarketListing.zone_normalized)
        .where(MarketListing.zone_normalized != None)  # noqa: E711
        .where(MarketListing.is_active == True)
        .distinct()
        .order_by(MarketListing.zone_normalized)
    )
    if city_id is not None:
        query = query.where(MarketListing.city_id == city_id)

    rows = session.exec(query).all()
    return [r for r in rows if r is not None]


@router.post("/listings")
def create_market_listing(
    listing_data: MarketListingCreate,
    session: Session = Depends(get_session),
):
    """Endpoint folosit de scraper — fără auth pentru a permite import automat."""
    existing = session.exec(
        select(MarketListing).where(MarketListing.url == listing_data.url)
    ).first()

    if existing:
        updated = False
        if existing.published_at is None and listing_data.published_at is not None:
            existing.published_at = listing_data.published_at
            updated = True
        if existing.city_id is None and listing_data.city_id is not None:
            existing.city_id = listing_data.city_id
            updated = True
        if existing.zone_normalized is None and listing_data.zone_normalized is not None:
            existing.zone_normalized = listing_data.zone_normalized
            updated = True
        if existing.zone_raw is None and listing_data.zone_raw is not None:
            existing.zone_raw = listing_data.zone_raw
            updated = True

        raw = session.get(MarketListingRaw, existing.raw_listing_id)
        raw_payload = (raw.raw_payload or {}) if raw else {}

        if raw and not raw_payload.get("image_urls") and listing_data.image_urls:
            raw.raw_payload = {
                **raw_payload,
                "image_urls": listing_data.image_urls,
                "data_quality": listing_data.data_quality,
                "quality_warnings": listing_data.quality_warnings,
            }
            raw_payload = raw.raw_payload
            session.add(raw)
            updated = True

        if updated:
            session.add(existing)
            session.commit()
            session.refresh(existing)

        return _listing_with_quality(
            existing, raw_payload, raw.location_raw if raw else None
        )

    # Calculăm preț/mp
    price_per_m2 = None
    if listing_data.price_eur and listing_data.surface_m2 and listing_data.surface_m2 > 0:
        price_per_m2 = listing_data.price_eur / listing_data.surface_m2

    raw_listing = MarketListingRaw(
        source_id=listing_data.source_id,
        external_id=listing_data.external_id,
        url=listing_data.url,
        title_raw=listing_data.title,
        description_raw=listing_data.description,
        price_raw=str(listing_data.price_eur) if listing_data.price_eur else None,
        city_raw=None,
        location_raw=listing_data.location_raw,
        surface_raw=str(listing_data.surface_m2) if listing_data.surface_m2 else None,
        rooms_raw=str(listing_data.rooms) if listing_data.rooms else None,
        raw_payload={
            "created_from": "scraper",
            "data_quality": listing_data.data_quality,
            "quality_warnings": listing_data.quality_warnings,
            "image_urls": listing_data.image_urls,
        },
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(raw_listing)
    session.commit()
    session.refresh(raw_listing)

    market_listing = MarketListing(
        raw_listing_id=raw_listing.id,
        source_id=listing_data.source_id,
        city_id=listing_data.city_id,
        url=listing_data.url,
        title=listing_data.title,
        description=listing_data.description,
        price_eur=listing_data.price_eur,
        currency=listing_data.currency,
        rooms=listing_data.rooms,
        surface_m2=listing_data.surface_m2,
        price_per_m2=price_per_m2,
        property_type=listing_data.property_type,
        transaction_type=listing_data.transaction_type,
        published_at=listing_data.published_at,
        zone_raw=listing_data.zone_raw,
        zone_normalized=listing_data.zone_normalized,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(market_listing)
    session.commit()
    session.refresh(market_listing)

    return _listing_with_quality(
        market_listing,
        {
            "data_quality": listing_data.data_quality,
            "quality_warnings": listing_data.quality_warnings,
            "image_urls": listing_data.image_urls,
        },
        listing_data.location_raw,
    )


# ── Endpoints protejate cu autentificare ───────────────────────────────────────

def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _apply_listing_filters(
    query,
    session: Session,
    *,
    city_id: int | None = None,
    zone: str | None = None,
    rooms: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    max_price_per_m2: float | None = None,
    min_surface: float | None = None,
    max_surface: float | None = None,
    source_slug: str | None = None,
    property_type: str | None = None,
    transaction_type: str | None = None,
    seller_type: str | None = None,
    locality: str | None = None,
    q: str | None = None,
    new_days: int | None = None,
):
    """Filtrele comune pentru listă, sumar și extensie."""
    from datetime import timedelta
    from sqlalchemy import func, or_

    if city_id is not None:
        query = query.where(MarketListing.city_id == city_id)
    if zone:
        query = query.where(MarketListing.zone_normalized == zone)
    if rooms is not None:
        # 4 = „4+ camere”
        query = query.where(MarketListing.rooms >= 4) if rooms >= 4 else query.where(MarketListing.rooms == rooms)
    if min_price is not None:
        query = query.where(MarketListing.price_eur >= min_price)
    if max_price is not None:
        query = query.where(MarketListing.price_eur <= max_price)
    if max_price_per_m2 is not None:
        query = query.where(MarketListing.price_per_m2 <= max_price_per_m2)
    if min_surface is not None:
        query = query.where(MarketListing.surface_m2 >= min_surface)
    if max_surface is not None:
        query = query.where(MarketListing.surface_m2 <= max_surface)
    if source_slug:
        slugs = _csv(source_slug)
        ids = [s.id for s in session.exec(select(Source).where(Source.slug.in_(slugs))).all()]
        query = query.where(MarketListing.source_id.in_(ids or [-1]))
    if property_type:
        query = query.where(MarketListing.property_type.in_(_csv(property_type)))
    if transaction_type:
        query = query.where(MarketListing.transaction_type.in_(_csv(transaction_type)))
    if seller_type:
        query = query.where(MarketListing.seller_type.in_(_csv(seller_type)))
    if new_days:
        query = query.where(MarketListing.first_seen_at >= datetime.utcnow() - timedelta(days=new_days))
    if locality:
        # localitatea exactă din sursă (ex. „Micești”, „Sebeș”)
        raw_ids = select(MarketListingRaw.id).where(MarketListingRaw.location_raw.ilike(f"%{locality}%"))
        query = query.where(MarketListing.raw_listing_id.in_(raw_ids))
    if q:
        for word in [w for w in q.split() if len(w) > 1][:6]:
            like = f"%{word}%"
            query = query.where(or_(
                MarketListing.title.ilike(like),
                MarketListing.description.ilike(like),
                MarketListing.zone_raw.ilike(like),
            ))
    return query


@router.get("/listings")
def list_market_listings(
    city_id: int | None = None,
    zone: str | None = None,
    rooms: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    max_price_per_m2: float | None = None,
    min_surface: float | None = None,
    max_surface: float | None = None,
    data_quality: str | None = None,
    source_slug: str | None = None,
    property_type: str | None = None,       # apartment,house,land,commercial (virgulă = mai multe)
    transaction_type: str | None = None,    # sale / rent
    seller_type: str | None = None,         # private / agency / developer
    locality: str | None = None,
    q: str | None = None,
    new_days: int | None = None,
    sort: str = "new",      # new | price_eur | surface_m2 | price_per_m2 | published_at | days
    order: str = "desc",    # asc | desc
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    # Paginare pe server: toate anunțurile sunt accesibile, câte `limit` pe pagină
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    columns = {
        "new": MarketListing.first_seen_at,
        "days": MarketListing.first_seen_at,
        "price_eur": MarketListing.price_eur,
        "surface_m2": MarketListing.surface_m2,
        "price_per_m2": MarketListing.price_per_m2,
        "published_at": MarketListing.published_at,
    }
    col = columns.get(sort, MarketListing.first_seen_at)
    asc = order == "asc"
    if sort == "days":  # „zile pe piață” crescător = cele mai noi primele
        asc = not asc
    order_by = col.asc().nulls_last() if asc else col.desc().nulls_last()
    query = (
        select(MarketListing)
        .where(MarketListing.is_active == True)
        .where(MarketListing.listing_status != "inactive")
        .order_by(order_by, MarketListing.id.desc())
    )
    query = _apply_listing_filters(
        query, session,
        city_id=city_id, zone=zone, rooms=rooms, min_price=min_price, max_price=max_price,
        max_price_per_m2=max_price_per_m2, min_surface=min_surface, max_surface=max_surface,
        source_slug=source_slug, property_type=property_type, transaction_type=transaction_type,
        seller_type=seller_type, locality=locality, q=q, new_days=new_days,
    )

    query = query.offset(offset).limit(limit)
    listings = session.exec(query).all()

    if not listings:
        return []

    # Load all raws in one IN query — no N+1
    raw_ids = [l.raw_listing_id for l in listings]
    raws = session.exec(
        select(MarketListingRaw).where(MarketListingRaw.id.in_(raw_ids))
    ).all()
    raw_map = {r.id: r for r in raws}

    result = []
    for listing in listings:
        raw = raw_map.get(listing.raw_listing_id)
        raw_payload = (raw.raw_payload or {}) if raw else {}

        # Filter by data_quality from raw_payload if requested
        if data_quality is not None:
            listing_quality = raw_payload.get("data_quality", "valid")
            if listing_quality != data_quality:
                continue

        result.append(
            _listing_with_quality(listing, raw_payload, raw.location_raw if raw else None)
        )

    return result


@router.get("/listings/summary")
def listings_summary(
    city_id: int | None = None,
    zone: str | None = None,
    rooms: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    max_price_per_m2: float | None = None,
    min_surface: float | None = None,
    max_surface: float | None = None,
    source_slug: str | None = None,
    property_type: str | None = None,
    transaction_type: str | None = None,
    seller_type: str | None = None,
    locality: str | None = None,
    q: str | None = None,
    new_days: int | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Totaluri reale (nu doar din pagina încărcată) pentru filtrele date."""
    from datetime import timedelta
    from sqlalchemy import func

    base = (
        select(MarketListing.id)
        .where(MarketListing.is_active == True)  # noqa: E712
        .where(MarketListing.listing_status != "inactive")
    )
    base = _apply_listing_filters(
        base, session,
        city_id=city_id, zone=zone, rooms=rooms, min_price=min_price, max_price=max_price,
        max_price_per_m2=max_price_per_m2, min_surface=min_surface, max_surface=max_surface,
        source_slug=source_slug, property_type=property_type, transaction_type=transaction_type,
        seller_type=seller_type, locality=locality, q=q, new_days=new_days,
    ).subquery()

    ids = select(base.c.id)
    week_ago = datetime.utcnow() - timedelta(days=7)
    row = session.exec(
        select(
            func.count(MarketListing.id),
            func.count(MarketListing.id).filter(MarketListing.first_seen_at >= week_ago),
            func.avg(MarketListing.price_eur),
            func.avg(MarketListing.price_per_m2),
        ).where(MarketListing.id.in_(ids))
    ).one()
    by_seller = dict(session.exec(
        select(MarketListing.seller_type, func.count(MarketListing.id))
        .where(MarketListing.id.in_(ids))
        .group_by(MarketListing.seller_type)
    ).all())
    by_type = dict(session.exec(
        select(MarketListing.property_type, func.count(MarketListing.id))
        .where(MarketListing.id.in_(ids))
        .group_by(MarketListing.property_type)
    ).all())
    return {
        "total": int(row[0] or 0),
        "new_7d": int(row[1] or 0),
        "avg_price_eur": round(row[2]) if row[2] else None,
        "avg_price_per_m2": round(row[3]) if row[3] else None,
        "by_seller_type": {str(k or "unknown"): v for k, v in by_seller.items()},
        "by_property_type": {str(k or "unknown"): v for k, v in by_type.items()},
    }


@router.post("/listings/refresh-images")
def refresh_listing_images(
    limit: int = 20,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Completează imaginile lipsă pentru anunțurile existente."""
    raw_listings = session.exec(select(MarketListingRaw).limit(300)).all()

    updated = 0
    skipped = 0

    for raw in raw_listings:
        payload = raw.raw_payload or {}
        if payload.get("image_urls"):
            skipped += 1
            continue
        if updated >= limit:
            break

        images = fetch_images_for_url(raw.url)
        if images:
            raw.raw_payload = {**payload, "image_urls": images}
            session.add(raw)
            updated += 1
            print(f"  ✓ {raw.url[:70]} → {len(images)} imagini")
        else:
            skipped += 1

    session.commit()

    return {
        "updated": updated,
        "skipped": skipped,
        "message": f"Imagini adăugate la {updated} anunțuri.",
    }
