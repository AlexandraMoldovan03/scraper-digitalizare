"""extend scrape_jobs with orchestration fields

Revision ID: f7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-27 00:00:00.000000

Adaugă câmpuri necesare pentru orchestrare completă:
- source_name, trigger_type, queued_at
- pages_total, pages_processed
- listings_created, listings_unchanged, listings_failed, warnings_count
- ALTER started_at → nullable (joburi în stare queued nu au started_at)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f7b8c9d0e1f2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # started_at trebuie să fie nullable pentru joburi în starea queued
    op.alter_column('scrape_jobs', 'started_at', nullable=True)

    op.add_column('scrape_jobs', sa.Column('source_name', sa.VARCHAR(100), nullable=True))
    op.add_column('scrape_jobs', sa.Column('trigger_type', sa.VARCHAR(20), nullable=True, server_default='manual'))
    op.add_column('scrape_jobs', sa.Column('queued_at', sa.DateTime(), nullable=True))
    op.add_column('scrape_jobs', sa.Column('pages_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scrape_jobs', sa.Column('pages_processed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scrape_jobs', sa.Column('listings_created', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scrape_jobs', sa.Column('listings_unchanged', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scrape_jobs', sa.Column('listings_failed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scrape_jobs', sa.Column('warnings_count', sa.Integer(), nullable=False, server_default='0'))

    op.create_index('ix_scrape_jobs_source_name', 'scrape_jobs', ['source_name'])


def downgrade() -> None:
    op.drop_index('ix_scrape_jobs_source_name', table_name='scrape_jobs')

    op.drop_column('scrape_jobs', 'warnings_count')
    op.drop_column('scrape_jobs', 'listings_failed')
    op.drop_column('scrape_jobs', 'listings_unchanged')
    op.drop_column('scrape_jobs', 'listings_created')
    op.drop_column('scrape_jobs', 'pages_processed')
    op.drop_column('scrape_jobs', 'pages_total')
    op.drop_column('scrape_jobs', 'queued_at')
    op.drop_column('scrape_jobs', 'trigger_type')
    op.drop_column('scrape_jobs', 'source_name')

    op.alter_column('scrape_jobs', 'started_at', nullable=False)
