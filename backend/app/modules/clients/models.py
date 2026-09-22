from datetime import datetime
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class Client(SQLModel, table=True):
    __tablename__ = "clients"

    id: int | None = Field(default=None, primary_key=True)

    organization_id: int = Field(foreign_key="organizations.id", index=True)
    assigned_user_id: int | None = Field(default=None, foreign_key="users.id", index=True)

    full_name: str = Field(max_length=200, index=True)
    phone: str | None = Field(default=None, max_length=50, index=True)
    email: str | None = Field(default=None, max_length=255, index=True)

    client_type: str = Field(default="buyer", max_length=50, index=True)

    budget_min_eur: float | None = Field(default=None, index=True)
    budget_max_eur: float | None = Field(default=None, index=True)

    preferred_city_id: int | None = Field(default=None, foreign_key="cities.id", index=True)

    min_rooms: int | None = Field(default=None)
    max_rooms: int | None = Field(default=None)

    min_surface_m2: float | None = Field(default=None)

    notes: str | None = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
