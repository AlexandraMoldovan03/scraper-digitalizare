"""
Market service — logică de business.
Folosită direct de orchestratorul de scraping (fără HTTP self-calls).

Deduplicare:
  1. (source_id, external_id) — identificare principală
  2. (source_id, canonical_url) — fallback dacă external_id lipsește
"""
import unicodedata
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.modules.market.models import (
    City, MarketListing, MarketListingRaw, PriceHistory, Source
)


# ── Câmpuri care contează pentru detectarea modificărilor ─────────────────────
_CHANGE_FIELDS = (
    "price_eur", "title", "description", "rooms",
    "surface_m2", "seller_type", "property_type", "transaction_type",
)

_PRICE_EPSILON = 0.01  # EUR — ignorăm diferențe sub 1 eurocent


def _values_equal(a: Any, b: Any) -> bool:
    """Compară două valori ignorând whitespace și casing nesemnificativ."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < _PRICE_EPSILON
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return a == b


def _strip_diacritics(text: str) -> str:
    """
    Normalizează pentru comparare: fără diacritice, lowercase, fără spații extra.
    'Sebeș' și 'Sebes' devin ambele 'sebes'.
    """
    # î și â sunt același sunet, diferă doar convenția ortografică:
    # SIRUTA scrie „Vîltori”, sursele moderne scriu „Vâltori”.
    unified = text.replace("î", "â").replace("Î", "Â")

    decomposed = unicodedata.normalize("NFKD", unified)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    # ș/ț cu virgulă vs sedilă nu se descompun mereu identic
    without_marks = (
        without_marks
        .replace("ș", "s").replace("Ș", "S")
        .replace("ţ", "t").replace("Ţ", "T")
        .replace("ș", "s").replace("ț", "t")
    )
    return " ".join(without_marks.lower().split())


def get_city_id_by_name(
    session: Session,
    name: str,
    county: str | None = None,
) -> int | None:
    """
    Caută city_id după nume. Nu creează orașe noi.

    `county` dezambiguizează localitățile omonime: 251 de nume se repetă
    între Alba și județele vecine (ex. Stejeriș există în Cluj și în Mureș).
    Când sursa ne dă județul, îl folosim; altfel preferăm Alba.

    Ordinea încercărilor:
      1. nume + județ, potrivire directă
      2. nume + județ, fără diacritice
      3. doar nume, preferând Alba dacă există mai multe potriviri
    """
    if not name:
        return None

    cleaned = name.strip()
    if not cleaned:
        return None

    target = _strip_diacritics(cleaned)
    if not target:
        return None

    county_target = _strip_diacritics(county) if county else None

    # ── 1 + 2. Cu județ ───────────────────────────────────────────────────────
    if county_target:
        city = session.exec(
            select(City)
            .where(City.name.ilike(cleaned))
            .where(City.county.ilike(county.strip()))
        ).first()
        if city:
            return city.id

        for candidate in session.exec(select(City)).all():
            if (
                _strip_diacritics(candidate.name) == target
                and _strip_diacritics(candidate.county or "") == county_target
            ):
                return candidate.id

    # ── 3. Doar nume, cu preferință pentru Alba ───────────────────────────────
    matches = [
        c for c in session.exec(select(City)).all()
        if _strip_diacritics(c.name) == target
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].id

    for candidate in matches:
        if _strip_diacritics(candidate.county or "") == "alba":
            return candidate.id
    return matches[0].id


def get_source_by_name(session: Session, name: str) -> Source | None:
    return session.exec(
        select(Source).where(Source.name.ilike(name))
    ).first()


def save_listing(
    session: Session,
    *,
    source_id: int,
    city_id: int | None,
    external_id: str | None,
    url: str,
    title: str | None,
    description: str | None,
    price_eur: float | None,
    currency: str = "EUR",
    rooms: int | None,
    surface_m2: float | None,
    property_type: str | None,
    transaction_type: str | None,
    location_raw: str | None,
    published_at: datetime | None,
    zone_raw: str | None,
    zone_normalized: str | None,
    data_quality: str = "valid",
    quality_warnings: list[str] | None = None,
    image_urls: list[str] | None = None,
    seller_type: str | None = None,
    job_id: int | None = None,
) -> tuple[str, MarketListing]:
    """
    Insert-or-update a single listing.

    Deduplicare:
      1. (source_id, external_id) dacă external_id există
      2. (source_id, url) altfel

    Returns:
        ("created" | "updated" | "unchanged", listing)
    """
    quality_warnings = quality_warnings or []
    image_urls = image_urls or []

    # ── 1. Lookup existent ────────────────────────────────────────────────────
    existing: MarketListing | None = None
    existing_raw: MarketListingRaw | None = None

    if external_id:
        # Lookup principal: (source_id, external_id) prin MarketListingRaw
        existing_raw = session.exec(
            select(MarketListingRaw)
            .where(MarketListingRaw.source_id == source_id)
            .where(MarketListingRaw.external_id == external_id)
        ).first()
        if existing_raw:
            existing = session.exec(
                select(MarketListing)
                .where(MarketListing.raw_listing_id == existing_raw.id)
            ).first()

    if existing is None:
        # Fallback: lookup pe URL
        existing = session.exec(
            select(MarketListing).where(MarketListing.url == url)
        ).first()
        if existing and existing_raw is None:
            existing_raw = session.get(MarketListingRaw, existing.raw_listing_id)

    # ── 2. Update existent ────────────────────────────────────────────────────
    if existing:
        changed_fields = []

        # Detectăm câmpuri schimbate
        new_vals = {
            "price_eur": price_eur,
            "title": title,
            "description": description,
            "rooms": rooms,
            "surface_m2": surface_m2,
            "seller_type": seller_type,
            "property_type": property_type,
            "transaction_type": transaction_type,
        }
        for field_name in _CHANGE_FIELDS:
            old_val = getattr(existing, field_name, None)
            new_val = new_vals.get(field_name)
            if not _values_equal(old_val, new_val) and new_val is not None:
                changed_fields.append(field_name)

        # Actualizare câmpuri auxiliare (fără a număra ca modificare)
        if existing.city_id is None and city_id is not None:
            existing.city_id = city_id
        if existing.published_at is None and published_at is not None:
            existing.published_at = published_at
        if existing.zone_raw is None and zone_raw is not None:
            existing.zone_raw = zone_raw
        if existing.zone_normalized is None and zone_normalized is not None:
            existing.zone_normalized = zone_normalized
        if existing.seller_type is None and seller_type is not None and not changed_fields:
            existing.seller_type = seller_type

        # Actualizare raw payload imagini
        raw = existing_raw or session.get(MarketListingRaw, existing.raw_listing_id)
        raw_updated = False
        if raw:
            raw_payload = raw.raw_payload or {}
            if not raw_payload.get("image_urls") and image_urls:
                raw.raw_payload = {
                    **raw_payload,
                    "image_urls": image_urls,
                    "data_quality": data_quality,
                    "quality_warnings": quality_warnings,
                }
                session.add(raw)
                raw_updated = True
            # Corectăm location_raw cand cel stocat e generic sau nefolosibil.
            # Scraperul e sursa de adevar: daca valoarea veche nu se rezolva la
            # un oras cunoscut (ex. un titlu de anunt salvat gresit), o inlocuim.
            if location_raw and location_raw.strip():
                stored = (raw.location_raw or "").strip()
                stored_is_unusable = (
                    not stored
                    or stored.lower() == "alba"
                    or get_city_id_by_name(session, stored) is None
                )
                if stored_is_unusable and location_raw.strip() != stored:
                    raw.location_raw = location_raw.strip()
                    session.add(raw)

        existing.last_seen_at = datetime.utcnow()
        existing.missing_count = 0
        existing.listing_status = "active"

        if changed_fields:
            # Aplicăm modificările
            for field_name in changed_fields:
                setattr(existing, field_name, new_vals[field_name])

            # Recalculăm price_per_m2 dacă s-a schimbat prețul sau suprafața
            if "price_eur" in changed_fields or "surface_m2" in changed_fields:
                p = existing.price_eur
                s = existing.surface_m2
                existing.price_per_m2 = (p / s) if p and s and s > 0 else None

            existing.last_changed_at = datetime.utcnow()
            existing.last_changed_by_scrape_job_id = job_id
            existing.latest_run_state = "modified"

            # PriceHistory doar la modificare numerică de preț
            if "price_eur" in changed_fields and price_eur is not None:
                ph = PriceHistory(
                    listing_id=existing.id,
                    price_eur=price_eur,
                    currency=currency,
                    recorded_at=datetime.utcnow(),
                    scrape_job_id=job_id,
                )
                session.add(ph)

            session.add(existing)
            session.commit()
            session.refresh(existing)
            return "updated", existing

        # Nicio schimbare semnificativă
        existing.latest_run_state = "unchanged"
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return "unchanged", existing

    # ── 3. Creare nouă ────────────────────────────────────────────────────────
    price_per_m2 = None
    if price_eur and surface_m2 and surface_m2 > 0:
        price_per_m2 = price_eur / surface_m2

    raw_listing = MarketListingRaw(
        source_id=source_id,
        external_id=external_id,
        url=url,
        title_raw=title,
        description_raw=description,
        price_raw=str(price_eur) if price_eur else None,
        location_raw=location_raw,
        surface_raw=str(surface_m2) if surface_m2 else None,
        rooms_raw=str(rooms) if rooms else None,
        raw_payload={
            "created_from": "scraper",
            "data_quality": data_quality,
            "quality_warnings": quality_warnings,
            "image_urls": image_urls,
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
        source_id=source_id,
        city_id=city_id,
        url=url,
        title=title,
        description=description,
        price_eur=price_eur,
        currency=currency,
        rooms=rooms,
        surface_m2=surface_m2,
        price_per_m2=price_per_m2,
        property_type=property_type,
        transaction_type=transaction_type,
        seller_type=seller_type,
        published_at=published_at,
        zone_raw=zone_raw,
        zone_normalized=zone_normalized,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        is_active=True,
        listing_status="active",
        missing_count=0,
        latest_run_state="new",
        created_by_scrape_job_id=job_id,
    )
    session.add(market_listing)
    session.commit()
    session.refresh(market_listing)

    return "created", market_listing


def mark_inactive_listings(
    session: Session,
    source_id: int,
    seen_external_ids: set[str],
    seen_urls: set[str],
    threshold: int = 3,
) -> dict:
    """
    Incrementează missing_count pentru listing-urile nevăzute în scanarea curentă.
    Apelat doar dacă jobul s-a încheiat cu succes.

    Returns:
        {"possibly_inactive": N, "inactive": N, "reset_to_active": N}
    """
    possibly_inactive = inactive = reset_to_active = 0

    # Obținem toate listing-urile active ale sursei
    raw_listings = session.exec(
        select(MarketListingRaw)
        .where(MarketListingRaw.source_id == source_id)
        .where(MarketListingRaw.is_active == True)
    ).all()

    raw_ids = [r.id for r in raw_listings]
    if not raw_ids:
        return {"possibly_inactive": 0, "inactive": 0, "reset_to_active": 0}

    listings = session.exec(
        select(MarketListing)
        .where(MarketListing.raw_listing_id.in_(raw_ids))
        .where(MarketListing.listing_status != "inactive")
    ).all()

    for listing in listings:
        raw = session.get(MarketListingRaw, listing.raw_listing_id)
        ext_id = raw.external_id if raw else None
        url = listing.url

        was_seen = (
            (ext_id and ext_id in seen_external_ids)
            or (url and url in seen_urls)
        )

        if was_seen:
            if listing.missing_count > 0:
                listing.missing_count = 0
                listing.listing_status = "active"
                reset_to_active += 1
                session.add(listing)
        else:
            listing.missing_count = (listing.missing_count or 0) + 1
            if listing.missing_count >= threshold:
                listing.listing_status = "inactive"
                inactive += 1
            else:
                listing.listing_status = "possibly_inactive"
                possibly_inactive += 1
            session.add(listing)

    session.commit()
    return {
        "possibly_inactive": possibly_inactive,
        "inactive": inactive,
        "reset_to_active": reset_to_active,
    }
