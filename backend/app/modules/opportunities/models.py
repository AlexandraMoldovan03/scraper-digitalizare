from datetime import datetime
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class Opportunity(SQLModel, table=True):
    __tablename__ = "opportunities"

    id: int | None = Field(default=None, primary_key=True)

    organization_id: int = Field(foreign_key="organizations.id", index=True)

    property_id: int = Field(foreign_key="properties.id", index=True)
    market_listing_id: int | None = Field(default=None, foreign_key="market_listings.id", index=True)
    client_id: int | None = Field(default=None, foreign_key="clients.id", index=True)

    score: float = Field(default=0, index=True)
    reason: str | None = Field(default=None, sa_column=Column(Text))

    status: str = Field(default="new", max_length=50, index=True)
    assigned_user_id: int | None = Field(default=None, foreign_key="users.id", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
