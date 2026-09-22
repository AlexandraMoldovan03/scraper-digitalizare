from collections.abc import Callable

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.database.session import get_session
from app.modules.auth.service import decode_token
from app.modules.users.models import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> User:
    """Validează token-ul și impune single-session."""
    invalid_exc = HTTPException(
        status_code=401,
        detail="Token invalid sau expirat. Te rog autentifică-te.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
        session_id: str = payload["session_id"]
    except Exception:
        raise invalid_exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise invalid_exc

    if user.session_id != session_id:
        raise HTTPException(
            status_code=401,
            detail="Sesiunea a expirat — te-ai autentificat pe alt dispozitiv.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_organization_id(
    current_user: User = Depends(get_current_user),
) -> int:
    return current_user.organization_id


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    allowed = set(allowed_roles)

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        # admin are acces la orice endpoint
        if current_user.role == "admin":
            return current_user
        if current_user.role not in allowed:
            raise HTTPException(status_code=403, detail="Nu ai permisiunea necesară.")
        return current_user

    return dependency
