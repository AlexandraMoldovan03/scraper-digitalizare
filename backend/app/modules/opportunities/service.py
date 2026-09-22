"""
Opportunities service — logică extrasă din router.
Apelată direct de orchestratorul de scraping.
"""
from datetime import datetime

from sqlmodel import Session, select

from app.modules.clients.models import Client
from app.modules.market.models import MarketListing
from app.modules.opportunities.models import Opportunity
from app.modules.properties.models import (
    OrganizationProperty,
    PriceHistory,
    Property,
    PropertyMarketListing,
)


def listing_matches_client(
    listing: MarketListing, client: Client
) -> tuple[bool, float, str]:
    reasons = []
    score = 0.0

    if client.preferred_city_id and listing.city_id != client.preferred_city_id:
        return False, 0.0, "Orașul nu se potrivește."
    if client.preferred_city_id and listing.city_id == client.preferred_city_id:
        score += 25
        reasons.append("oraș potrivit")

    if client.budget_max_eur and listing.price_eur and listing.price_eur > client.budget_max_eur:
        return False, 0.0, "Prețul depășește bugetul maxim."
    if client.budget_max_eur and listing.price_eur:
        score += 25
        reasons.append("preț în buget")

    if client.min_rooms and listing.rooms and listing.rooms < client.min_rooms:
        return False, 0.0, "Număr prea mic de camere."
    if client.max_rooms and listing.rooms and listing.rooms > client.max_rooms:
        return False, 0.0, "Număr prea mare de camere."
    if listing.rooms:
        score += 20
        reasons.append("număr de camere potrivit")

    if client.min_surface_m2 and listing.surface_m2 and listing.surface_m2 < client.min_surface_m2:
        return False, 0.0, "Suprafața este prea mică."
    if client.min_surface_m2 and listing.surface_m2:
        score += 20
        reasons.append("suprafață potrivită")

    if listing.price_per_m2:
        score += 10
        reasons.append(f"preț/mp calculat: {round(listing.price_per_m2, 2)} EUR/mp")

    reason = "Se potrivește cu clientul: " + ", ".join(reasons) + "."
    return True, min(score, 100), reason


def get_or_create_property_from_listing(
    session: Session, listing: MarketListing
) -> Property:
    existing_link = session.exec(
        select(PropertyMarketListing).where(
            PropertyMarketListing.market_listing_id == listing.id
        )
    ).first()

    if existing_link:
        existing_property = session.get(Property, existing_link.property_id)
        if existing_property:
            return existing_property

    prop = Property(
        city_id=listing.city_id,
        title=listing.title,
        description_summary=listing.description,
        property_type=listing.property_type,
        transaction_type=listing.transaction_type,
        rooms=listing.rooms,
        surface_m2=listing.surface_m2,
        latitude=listing.latitude,
        longitude=listing.longitude,
        opportunity_score=0,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)

    link = PropertyMarketListing(
        property_id=prop.id,
        market_listing_id=listing.id,
        similarity_score=100,
        created_at=datetime.utcnow(),
    )
    session.add(link)

    if listing.price_eur:
        price_history = PriceHistory(
            property_id=prop.id,
            source_id=listing.source_id,
            price_eur=listing.price_eur,
            price_per_m2=listing.price_per_m2,
            detected_at=datetime.utcnow(),
        )
        session.add(price_history)

    session.commit()
    session.refresh(prop)
    return prop


def generate_opportunities_for_org(session: Session, org_id: int) -> dict:
    """
    Generează oportunități pentru o organizație.
    Returnează {"created": N, "skipped": N, "clients_checked": N, "listings_checked": N}
    """
    clients = session.exec(
        select(Client).where(Client.organization_id == org_id)
    ).all()

    listings = session.exec(
        select(MarketListing).where(MarketListing.is_active == True)
    ).all()

    created_count = 0
    skipped_count = 0

    for client in clients:
        for listing in listings:
            is_match, score, reason = listing_matches_client(listing, client)
            if not is_match:
                skipped_count += 1
                continue

            existing = session.exec(
                select(Opportunity).where(
                    Opportunity.organization_id == org_id,
                    Opportunity.market_listing_id == listing.id,
                    Opportunity.client_id == client.id,
                )
            ).first()
            if existing:
                skipped_count += 1
                continue

            prop = get_or_create_property_from_listing(session, listing)

            existing_org_prop = session.exec(
                select(OrganizationProperty).where(
                    OrganizationProperty.organization_id == org_id,
                    OrganizationProperty.property_id == prop.id,
                )
            ).first()
            if not existing_org_prop:
                session.add(OrganizationProperty(
                    organization_id=org_id,
                    property_id=prop.id,
                    status="new",
                    notes="Creat automat dintr-o oportunitate.",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                ))

            session.add(Opportunity(
                organization_id=org_id,
                property_id=prop.id,
                market_listing_id=listing.id,
                client_id=client.id,
                score=score,
                reason=reason,
                status="new",
                created_at=datetime.utcnow(),
            ))
            created_count += 1

    session.commit()

    return {
        "created": created_count,
        "skipped": skipped_count,
        "clients_checked": len(clients),
        "listings_checked": len(listings),
    }
