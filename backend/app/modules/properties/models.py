from datetime import datetime
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class Property(SQLModel, table=True):
    __tablename__ = "properties"

    id: int | None = Field(default=None, primary_key=True)

    city_id: int | None = Field(default=None, foreign_key="cities.id", index=True)

    title: str | None = Field(default=None, sa_column=Column(Text))
    description_summary: str | None = Field(default=None, sa_column=Column(Text))

    property_type: str | None = Field(default=None, max_length=50, index=True)
    transaction_type: str | None = Field(default=None, max_length=50, index=True)

    rooms: int | None = Field(default=None, index=True)
    surface_m2: float | None = Field(default=None, index=True)
    land_surface_m2: float | None = Field(default=None)

    floor: int | None = Field(default=None)
    total_floors: int | None = Field(default=None)
    year_built: int | None = Field(default=None)

    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    address_text: str | None = Field(default=None, sa_column=Column(Text))

    quality_score: float | None = Field(default=None, index=True)
    opportunity_score: float | None = Field(default=None, index=True)

    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PropertyMarketListing(SQLModel, table=True):
    __tablename__ = "property_market_listings"

    id: int | None = Field(default=None, primary_key=True)

    property_id: int = Field(foreign_key="properties.id", index=True)
    market_listing_id: int = Field(foreign_key="market_listings.id", index=True)

    similarity_score: float | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrganizationProperty(SQLModel, table=True):
    __tablename__ = "organization_properties"

    id: int | None = Field(default=None, primary_key=True)

    organization_id: int = Field(foreign_key="organizations.id", index=True)
    property_id: int = Field(foreign_key="properties.id", index=True)
    assigned_user_id: int | None = Field(default=None, foreign_key="users.id", index=True)

    status: str = Field(default="new", max_length=50, index=True)
    notes: str | None = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PriceHistory(SQLModel, table=True):
    __tablename__ = "property_price_history"

    id: int | None = Field(default=None, primary_key=True)

    property_id: int = Field(foreign_key="properties.id", index=True)
    source_id: int | None = Field(default=None, foreign_key="sources.id", index=True)

    price_eur: float | None = Field(default=None, index=True)
    price_per_m2: float | None = Field(default=None, index=True)

    detected_at: datetime = Field(default_factory=datetime.utcnow, index=True)
