from datetime import datetime
from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(max_length=100, index=True, unique=True)
    # slug = source_key din registry (ex: "publi24", "imobiliare_ro")
    # Folosit pentru lookup exact în orchestrator, fără ilike case-insensitive.
    slug: str | None = Field(default=None, max_length=100, index=True, unique=True)
    base_url: str = Field(max_length=500)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class City(SQLModel, table=True):
    __tablename__ = "cities"

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(max_length=150, index=True)
    county: str = Field(max_length=150, index=True)

    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    county_code: str | None = Field(default="AB", max_length=10)
    locality_type: str | None = Field(default=None, max_length=50)

    is_active: bool = Field(default=True)


class MarketListingRaw(SQLModel, table=True):
    __tablename__ = "market_listings_raw"

    id: int | None = Field(default=None, primary_key=True)

    source_id: int = Field(foreign_key="sources.id", index=True)

    external_id: str | None = Field(default=None, max_length=255, index=True)
    url: str = Field(sa_column=Column(Text, unique=True, nullable=False))

    title_raw: str | None = Field(default=None, sa_column=Column(Text))
    description_raw: str | None = Field(default=None, sa_column=Column(Text))

    price_raw: str | None = Field(default=None, max_length=100)
    city_raw: str | None = Field(default=None, max_length=150)
    location_raw: str | None = Field(default=None, sa_column=Column(Text))
    surface_raw: str | None = Field(default=None, max_length=100)
    rooms_raw: str | None = Field(default=None, max_length=100)

    raw_payload: dict | None = Field(default=None, sa_column=Column(JSON))
    raw_data_hash: str | None = Field(default=None, max_length=255, index=True)

    first_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    is_active: bool = Field(default=True)


class MarketListing(SQLModel, table=True):
    __tablename__ = "market_listings"

    id: int | None = Field(default=None, primary_key=True)

    raw_listing_id: int = Field(foreign_key="market_listings_raw.id", index=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="cities.id", index=True)

    url: str = Field(sa_column=Column(Text, unique=True, nullable=False))

    title: str | None = Field(default=None, sa_column=Column(Text))
    description: str | None = Field(default=None, sa_column=Column(Text))

    price_eur: float | None = Field(default=None, index=True)
    currency: str | None = Field(default=None, max_length=10)

    rooms: int | None = Field(default=None, index=True)
    surface_m2: float | None = Field(default=None, index=True)
    price_per_m2: float | None = Field(default=None, index=True)

    property_type: str | None = Field(default=None, max_length=50, index=True)
    transaction_type: str | None = Field(default=None, max_length=50, index=True)

    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    published_at: datetime | None = Field(default=None)
    first_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    zone_raw: str | None = Field(default=None, max_length=255)
    zone_normalized: str | None = Field(default=None, max_length=255, index=True)

    is_active: bool = Field(default=True)

    # ── Câmpuri extinse ────────────────────────────────────────────────────────
    seller_type: str | None = Field(default=None, max_length=50, index=True)
    latest_run_state: str | None = Field(default=None, max_length=50)
    created_by_scrape_job_id: int | None = Field(default=None)
    last_changed_at: datetime | None = Field(default=None)
    last_changed_by_scrape_job_id: int | None = Field(default=None)
    listing_status: str = Field(default="active", max_length=50, index=True)
    missing_count: int = Field(default=0)


class PriceHistory(SQLModel, table=True):
    __tablename__ = "price_history"
    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="market_listings.id", index=True)
    price_eur: float | None = Field(default=None)
    currency: str | None = Field(default=None, max_length=10)
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    scrape_job_id: int | None = Field(default=None)
