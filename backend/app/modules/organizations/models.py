from datetime import datetime
from sqlmodel import Field, SQLModel


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(max_length=200, index=True)
    slug: str = Field(max_length=100, index=True, unique=True)

    subscription_plan: str = Field(default="free", max_length=50)
    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
