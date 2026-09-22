from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database.session import get_session
from app.modules.organizations.models import Organization


router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/")
def list_organizations(session: Session = Depends(get_session)):
    statement = select(Organization).order_by(Organization.name)
    return session.exec(statement).all()
