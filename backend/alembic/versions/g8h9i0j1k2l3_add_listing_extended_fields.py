"""add listing extended fields and price_history

Revision ID: g8h9i0j1k2l3
Revises: a1b2c3d4e5f6
Create Date: 2026-07-31 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = 'g8h9i0j1k2l3'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Câmpuri noi pe market_listings — IF NOT EXISTS pentru idempotență
    new_columns = [
        ("seller_type", "VARCHAR(50)"),
        ("latest_run_state", "VARCHAR(50)"),
        ("created_by_scrape_job_id", "INTEGER"),
        ("last_changed_at", "TIMESTAMP WITHOUT TIME ZONE"),
        ("last_changed_by_scrape_job_id", "INTEGER"),
        ("listing_status", "VARCHAR(50) NOT NULL DEFAULT 'active'"),
        ("missing_count", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col_name, col_def in new_columns:
        conn.execute(sa.text(
            f"ALTER TABLE market_listings ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
        ))

    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_market_listings_seller_type "
        "ON market_listings (seller_type)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_market_listings_listing_status "
        "ON market_listings (listing_status)"
    ))

    # 2. Tabel price_history
    # Dacă există deja o tabelă price_history cu schema veche (property_id în loc de listing_id),
    # o redenumim în property_price_history, apoi creăm tabela nouă corectă.
    has_listing_id = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'price_history' AND column_name = 'listing_id'
    """)).fetchone()

    has_old_table = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'price_history'
    """)).fetchone()

    has_new_table_already = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'property_price_history'
    """)).fetchone()

    if has_old_table and not has_listing_id:
        # Tabelă veche cu schema properties — redenumire
        if not has_new_table_already:
            conn.execute(sa.text(
                "ALTER TABLE price_history RENAME TO property_price_history"
            ))
        else:
            # Ambele există — tabelă veche orfană, o ștergem
            conn.execute(sa.text("DROP TABLE price_history"))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS price_history (
            id SERIAL NOT NULL,
            listing_id INTEGER NOT NULL REFERENCES market_listings (id),
            price_eur FLOAT,
            currency VARCHAR(10),
            recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            scrape_job_id INTEGER,
            PRIMARY KEY (id)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_price_history_listing_id "
        "ON price_history (listing_id)"
    ))

    # 3. Activează sursa imobiliare_ro
    conn.execute(sa.text(
        "UPDATE sources SET is_active = TRUE WHERE slug = 'imobiliare_ro'"
    ))


def downgrade() -> None:
    # Dezactivează sursa
    op.execute("UPDATE sources SET is_active = FALSE WHERE slug = 'imobiliare_ro'")

    # Drop price_history
    op.drop_index('ix_price_history_listing_id', table_name='price_history')
    op.drop_table('price_history')

    # Drop coloane din market_listings
    op.drop_index('ix_market_listings_listing_status', table_name='market_listings')
    op.drop_index('ix_market_listings_seller_type', table_name='market_listings')
    op.drop_column('market_listings', 'missing_count')
    op.drop_column('market_listings', 'listing_status')
    op.drop_column('market_listings', 'last_changed_by_scrape_job_id')
    op.drop_column('market_listings', 'last_changed_at')
    op.drop_column('market_listings', 'created_by_scrape_job_id')
    op.drop_column('market_listings', 'latest_run_state')
    op.drop_column('market_listings', 'seller_type')
