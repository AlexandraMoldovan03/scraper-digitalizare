from datetime import datetime
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: int | None = Field(default=None, primary_key=True)

    organization_id: int = Field(foreign_key="organizations.id", index=True)
    assigned_user_id: int | None = Field(default=None, foreign_key="users.id", index=True)

    related_client_id: int | None = Field(default=None, foreign_key="clients.id", index=True)
    related_property_id: int | None = Field(default=None, foreign_key="properties.id", index=True)

    title: str = Field(max_length=255, index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))

    due_at: datetime | None = Field(default=None, index=True)
    status: str = Field(default="todo", max_length=50, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
