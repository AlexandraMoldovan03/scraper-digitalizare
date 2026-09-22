from datetime import datetime
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)

    organization_id: int = Field(foreign_key="organizations.id", index=True)

    email: str = Field(max_length=255, index=True, unique=True)
    password_hash: str = Field(max_length=255)

    full_name: str = Field(max_length=200)
    role: str = Field(default="agent", max_length=50, index=True)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Single-session enforcement: regenerated on each login
    session_id: str | None = Field(default=None, max_length=255)
    last_login_at: datetime | None = Field(default=None)
