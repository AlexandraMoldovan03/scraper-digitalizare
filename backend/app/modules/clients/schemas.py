from sqlmodel import SQLModel


class ClientCreate(SQLModel):
    full_name: str
    phone: str | None = None
    email: str | None = None

    client_type: str = "buyer"

    budget_min_eur: float | None = None
    budget_max_eur: float | None = None

    preferred_city_id: int | None = None

    min_rooms: int | None = None
    max_rooms: int | None = None

    min_surface_m2: float | None = None

    notes: str | None = None
