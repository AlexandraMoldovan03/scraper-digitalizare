from datetime import datetime

from sqlmodel import SQLModel


class CityCreate(SQLModel):
    name: str
    county: str = "Alba"


class MarketListingCreate(SQLModel):
    source_id: int
    city_id: int | None = None

    external_id: str | None = None
    url: str

    title: str
    description: str | None = None

    price_eur: float | None = None
    currency: str = "EUR"

    rooms: int | None = None
    surface_m2: float | None = None

    property_type: str = "apartment"
    transaction_type: str = "sale"

    location_raw: str | None = None

    published_at: datetime | None = None

    zone_raw: str | None = None
    zone_normalized: str | None = None

    # Câmpuri de calitate + imagini — stocate în raw_payload, fără migrație
    data_quality: str = "valid"
    quality_warnings: list[str] = []
    image_urls: list[str] = []
