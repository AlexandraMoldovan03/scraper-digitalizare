"""seed romimo source row

Revision ID: i0j1k2l3m4n5
Revises: g8h9i0j1k2l3
Create Date: 2026-08-06 12:00:00.000000

Adaugă rândul pentru sursa Romimo în tabelul `sources`.
is_active=false implicit — se activează manual după prima importare verificată.

NU face ALTER TABLE — schema există deja.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "i0j1k2l3m4n5"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Evita duplicate dacă migrația e rulată de două ori
    existing = conn.execute(
        sa.text("SELECT id FROM sources WHERE slug = 'romimo' LIMIT 1")
    ).fetchone()

    if existing is None:
        conn.execute(
            sa.text("""
                INSERT INTO sources (name, slug, base_url, is_active, created_at)
                VALUES ('Romimo', 'romimo', 'https://www.romimo.ro', false, NOW())
            """)
        )


def downgrade() -> None:
    op.execute("DELETE FROM sources WHERE slug = 'romimo'")
