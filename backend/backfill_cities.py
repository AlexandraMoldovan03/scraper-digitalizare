"""
Backfill: re-potriveste city_id pentru anunturile care au location_raw
dar city_id NULL. Foloseste matcher-ul nou (fara diacritice).

Ruleaza: PYTHONPATH=. python backfill_cities.py
"""
from collections import Counter

from dotenv import load_dotenv
load_dotenv('/Users/alexandramoldovan/scraper-digitalizare/backend/.env')

from sqlmodel import Session, select

from app.database.session import engine
from app.modules.market.models import MarketListing, MarketListingRaw, Source
from app.modules.market.service import get_city_id_by_name

with Session(engine) as session:
    sources = {s.id: (s.slug or s.name) for s in session.exec(select(Source)).all()}

    rows = session.exec(
        select(MarketListing, MarketListingRaw)
        .join(MarketListingRaw, MarketListing.raw_listing_id == MarketListingRaw.id)
        .where(MarketListing.city_id == None)  # noqa: E711
    ).all()

    print(f"Anunturi fara city_id: {len(rows)}\n")

    fixed = 0
    still_unknown: Counter = Counter()
    by_source: Counter = Counter()

    for listing, raw in rows:
        loc = raw.location_raw
        if not loc:
            still_unknown["(fara location_raw)"] += 1
            continue

        city_id = get_city_id_by_name(session, loc)
        if city_id:
            listing.city_id = city_id
            session.add(listing)
            fixed += 1
            by_source[sources.get(listing.source_id, "?")] += 1
        else:
            still_unknown[loc] += 1

    session.commit()

    print(f"Reparate: {fixed}")
    for src, n in by_source.most_common():
        print(f"   {src}: {n}")

    print(f"\nRamase nepotrivite: {sum(still_unknown.values())}")
    for loc, n in still_unknown.most_common(25):
        print(f"   {loc!r}  x{n}")
