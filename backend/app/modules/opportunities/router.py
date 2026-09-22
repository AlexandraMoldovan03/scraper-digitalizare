from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database.session import get_session
from app.modules.auth.dependencies import (
    get_current_organization_id,
    get_current_user,
)
from app.modules.clients.models import Client
from app.modules.market.models import MarketListing
from app.modules.opportunities.models import Opportunity
from app.modules.opportunities.service import generate_opportunities_for_org
from app.modules.users.models import User


router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("/")
def list_opportunities(
    session: Session = Depends(get_session),
    organization_id: int = Depends(get_current_organization_id),
    _: User = Depends(get_current_user),
):
    statement = (
        select(Opportunity)
        .where(Opportunity.organization_id == organization_id)
        .order_by(Opportunity.created_at.desc())
    )
    return session.exec(statement).all()


@router.post("/generate")
def generate_opportunities(
    session: Session = Depends(get_session),
    organization_id: int = Depends(get_current_organization_id),
    _: User = Depends(get_current_user),
):
    return generate_opportunities_for_org(session, organization_id)


@router.get("/feed")
def opportunities_feed(
    session: Session = Depends(get_session),
    organization_id: int = Depends(get_current_organization_id),
    _: User = Depends(get_current_user),
):
    opportunities = session.exec(
        select(Opportunity)
        .where(Opportunity.organization_id == organization_id)
        .order_by(Opportunity.created_at.desc())
    ).all()

    result = []

    for opportunity in opportunities:
        client = (
            session.exec(
                select(Client).where(
                    Client.id == opportunity.client_id,
                    Client.organization_id == organization_id,
                )
            ).first()
            if opportunity.client_id
            else None
        )
        listing = session.get(MarketListing, opportunity.market_listing_id) if opportunity.market_listing_id else None

        result.append({
            "opportunity_id": opportunity.id,
            "score": opportunity.score,
            "status": opportunity.status,
            "reason": opportunity.reason,
            "created_at": opportunity.created_at,

            "client": {
                "id": client.id if client else None,
                "full_name": client.full_name if client else None,
                "phone": client.phone if client else None,
                "email": client.email if client else None,
                "budget_max_eur": client.budget_max_eur if client else None,
                "min_rooms": client.min_rooms if client else None,
                "max_rooms": client.max_rooms if client else None,
                "min_surface_m2": client.min_surface_m2 if client else None,
            } if client else None,

            "listing": {
                "id": listing.id if listing else None,
                "title": listing.title if listing else None,
                "url": listing.url if listing else None,
                "price_eur": listing.price_eur if listing else None,
                "rooms": listing.rooms if listing else None,
                "surface_m2": listing.surface_m2 if listing else None,
                "price_per_m2": listing.price_per_m2 if listing else None,
                "property_type": listing.property_type if listing else None,
                "transaction_type": listing.transaction_type if listing else None,
            } if listing else None,
        })

    return result
