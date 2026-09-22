"""add zone and city fields

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add zone columns to market_listings
    op.add_column('market_listings', sa.Column('zone_raw', sa.VARCHAR(255), nullable=True))
    op.add_column('market_listings', sa.Column('zone_normalized', sa.VARCHAR(255), nullable=True))
    op.create_index('ix_market_listings_zone_normalized', 'market_listings', ['zone_normalized'])

    # Add locality columns to cities
    op.add_column('cities', sa.Column('county_code', sa.VARCHAR(10), nullable=True, server_default='AB'))
    op.add_column('cities', sa.Column('locality_type', sa.VARCHAR(50), nullable=True))


def downgrade() -> None:
    op.drop_index('ix_market_listings_zone_normalized', table_name='market_listings')
    op.drop_column('market_listings', 'zone_normalized')
    op.drop_column('market_listings', 'zone_raw')

    op.drop_column('cities', 'locality_type')
    op.drop_column('cities', 'county_code')
