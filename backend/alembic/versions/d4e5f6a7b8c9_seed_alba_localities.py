"""seed alba localities

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCALITIES = [
    ("Alba Iulia", "Alba", "AB", "municipiu"),
    ("Aiud", "Alba", "AB", "municipiu"),
    ("Blaj", "Alba", "AB", "municipiu"),
    ("Sebeș", "Alba", "AB", "oraș"),
    ("Cugir", "Alba", "AB", "oraș"),
    ("Ocna Mureș", "Alba", "AB", "oraș"),
    ("Zlatna", "Alba", "AB", "oraș"),
    ("Abrud", "Alba", "AB", "oraș"),
    ("Câmpeni", "Alba", "AB", "oraș"),
    ("Baia de Arieș", "Alba", "AB", "oraș"),
    ("Teiuș", "Alba", "AB", "oraș"),
    ("Ciugud", "Alba", "AB", "comună"),
    ("Unirea", "Alba", "AB", "comună"),
    ("Cricău", "Alba", "AB", "comună"),
    ("Galda de Jos", "Alba", "AB", "comună"),
    ("Ighiu", "Alba", "AB", "comună"),
]


def upgrade() -> None:
    for name, county, county_code, locality_type in LOCALITIES:
        op.execute(sa.text(
            "INSERT INTO cities (name, county, county_code, locality_type, is_active) "
            "SELECT :name, :county, :county_code, :locality_type, TRUE "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM cities WHERE name = :name AND county_code = :county_code"
            ")"
        ).bindparams(
            name=name,
            county=county,
            county_code=county_code,
            locality_type=locality_type,
        ))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM cities WHERE county_code = 'AB'"))
