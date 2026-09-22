from datetime import datetime
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class ScrapeJob(SQLModel, table=True):
    __tablename__ = "scrape_jobs"

    id: int | None = Field(default=None, primary_key=True)

    # Source
    source_id: int | None = Field(default=None, foreign_key="sources.id", index=True)
    source_name: str | None = Field(default=None, max_length=100, index=True)
    city_id: int | None = Field(default=None, foreign_key="cities.id", index=True)

    # Trigger
    trigger_type: str = Field(default="manual", max_length=20)

    # Status
    status: str = Field(default="queued", max_length=50, index=True)

    # Timestamps
    queued_at: datetime | None = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = Field(default=None, index=True)
    finished_at: datetime | None = Field(default=None)

    # Progress
    pages_total: int = Field(default=0)
    pages_processed: int = Field(default=0)

    # Counters
    listings_found: int = Field(default=0)
    listings_created: int = Field(default=0)
    listings_updated: int = Field(default=0)
    listings_unchanged: int = Field(default=0)
    listings_failed: int = Field(default=0)
    warnings_count: int = Field(default=0)

    # Legacy counters (kept for backwards compat with old rows)
    listings_inserted: int = Field(default=0)

    error_message: str | None = Field(default=None, sa_column=Column(Text))
