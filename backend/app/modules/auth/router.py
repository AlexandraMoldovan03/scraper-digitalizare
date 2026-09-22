from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.service import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    email: str
    password: str
    full_name: str = "Administrator"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_session)):
    user = db.exec(select(User).where(User.email == data.email)).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email sau parolă incorecte.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cont dezactivat. Contactează administratorul.")

    # Generăm session_id nou → invalidează toate sesiunile active anterior
    new_session_id = str(uuid4())
    user.session_id = new_session_id
    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()

    token = create_access_token(user.id, user.email, new_session_id)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@router.post("/logout")
def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    current_user.session_id = None
    db.add(current_user)
    db.commit()
    return {"message": "Delogat cu succes."}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
    }


@router.post("/setup", summary="Creare administrator inițial")
def setup_first_admin(data: SetupRequest, db: Session = Depends(get_session)):
    """
    Creează primul cont de administrator.
    Funcționează DOAR dacă nu există niciun utilizator în sistem.
    """
    if db.exec(select(User)).first():
        raise HTTPException(
            status_code=403,
            detail="Setup deja realizat. Există utilizatori în sistem.",
        )

    from app.modules.organizations.models import Organization  # avoid circular
    org = db.get(Organization, 1)
    if not org:
        raise HTTPException(
            status_code=400,
            detail="Organizația cu ID=1 nu există. Rulează mai întâi migrațiile.",
        )

    user = User(
        organization_id=1,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": f"Administrator creat cu succes: {user.email}", "id": user.id}
