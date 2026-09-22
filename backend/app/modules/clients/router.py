from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database.session import get_session
from app.modules.auth.dependencies import (
    get_current_organization_id,
    get_current_user,
)
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate
from app.modules.users.models import User


router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/")
def list_clients(
    session: Session = Depends(get_session),
    organization_id: int = Depends(get_current_organization_id),
    _: User = Depends(get_current_user),
):
    statement = (
        select(Client)
        .where(Client.organization_id == organization_id)
        .order_by(Client.created_at.desc())
    )

    return session.exec(statement).all()


@router.post("/")
def create_client(
    client_data: ClientCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    client = Client(
        organization_id=current_user.organization_id,
        full_name=client_data.full_name,
        phone=client_data.phone,
        email=client_data.email,
        client_type=client_data.client_type,
        budget_min_eur=client_data.budget_min_eur,
        budget_max_eur=client_data.budget_max_eur,
        preferred_city_id=client_data.preferred_city_id,
        min_rooms=client_data.min_rooms,
        max_rooms=client_data.max_rooms,
        min_surface_m2=client_data.min_surface_m2,
        notes=client_data.notes,
    )

    session.add(client)
    session.commit()
    session.refresh(client)

    return client
