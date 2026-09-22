"""seed olx (și storia, dacă lipsește) în tabelul sources

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-09-22 12:00:00.000000

Adaugă sursa OLX (activă). Adaugă și Storia dacă nu a fost creată manual.
Idempotent: nu dublează rândurile existente.
"""
from alembic import op
import sqlalchemy as sa

revision = "j1k2l3m4n5o6"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None

SOURCES = [
    ("OLX", "olx", "https://www.olx.ro", True),
    ("Storia", "storia", "https://www.storia.ro", True),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, slug, base_url, active in SOURCES:
        exists = conn.execute(
            sa.text("SELECT id FROM sources WHERE slug = :slug OR lower(name) = lower(:name) LIMIT 1"),
            {"slug": slug, "name": name},
        ).fetchone()
        if exists is None:
            conn.execute(
                sa.text(
                    "INSERT INTO sources (name, slug, base_url, is_active, created_at) "
                    "VALUES (:name, :slug, :base_url, :active, NOW())"
                ),
                {"name": name, "slug": slug, "base_url": base_url, "active": active},
            )
        else:
            # rând existent fără slug (creat manual) → completăm slug-ul
            conn.execute(
                sa.text("UPDATE sources SET slug = :slug WHERE id = :id AND slug IS NULL"),
                {"slug": slug, "id": exists[0]},
            )


def downgrade() -> None:
    op.execute("DELETE FROM sources WHERE slug = 'olx'")
