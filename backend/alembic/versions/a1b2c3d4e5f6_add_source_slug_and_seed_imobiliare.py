"""add source slug and seed imobiliare_ro

Revision ID: a1b2c3d4e5f6
Revises: f7b8c9d0e1f2
Create Date: 2026-07-29 00:00:00.000000

Ce face această migrație:
  1. Adaugă coloana `slug` (VARCHAR 100, nullable) pe tabela `sources`.
  2. Populează slug-ul pentru sursele existente (publi24 → "publi24").
  3. Adaugă constraint NOT NULL + unique index pe slug.
  4. Inserează sursa Imobiliare.ro cu is_active=FALSE (idempotent).

Down:
  - Șterge sursa imobiliare_ro.
  - Șterge coloana slug.
"""
import sqlalchemy as sa
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'f7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Adaugă coloana slug (nullable temporar) ────────────────────────────
    op.add_column(
        'sources',
        sa.Column('slug', sa.String(100), nullable=True),
    )

    # ── 2. Backfill slug pentru sursele existente ─────────────────────────────
    op.execute(
        """
        UPDATE sources
        SET slug = LOWER(REPLACE(REPLACE(name, '.', '_'), ' ', '_'))
        WHERE slug IS NULL
        """
    )
    # Corecție specifică: publi24 → "publi24" (nu "publi24")
    op.execute("UPDATE sources SET slug = 'publi24' WHERE name ILIKE 'publi24'")

    # ── 3. NOT NULL + unique index ────────────────────────────────────────────
    op.alter_column('sources', 'slug', nullable=False)
    op.create_index('ix_sources_slug', 'sources', ['slug'], unique=True)

    # ── 4. Seed Imobiliare.ro (idempotent) ────────────────────────────────────
    op.execute(
        """
        INSERT INTO sources (name, slug, base_url, is_active, created_at)
        SELECT
            'Imobiliare.ro',
            'imobiliare_ro',
            'https://www.imobiliare.ro',
            FALSE,
            NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM sources WHERE slug = 'imobiliare_ro'
        )
        """
    )


def downgrade() -> None:
    # Șterge sursa imobiliare_ro (dacă există)
    op.execute("DELETE FROM sources WHERE slug = 'imobiliare_ro'")

    # Elimină index + coloană
    op.drop_index('ix_sources_slug', table_name='sources')
    op.drop_column('sources', 'slug')
