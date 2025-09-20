"""add receipt_items table

Revision ID: 20250920_025900
Revises: 20250920_024700
Create Date: 2025-09-20 02:59:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20250920_025900'
down_revision: str | None = '20250920_024700'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'receipt_items',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=512), nullable=False),
        sa.Column('price', sa.Numeric(12, 2), nullable=True),
        sa.Column('qty', sa.Integer(), nullable=True),
        sa.Column('kg_co2e', sa.Numeric(14, 6), nullable=True),
        sa.Column('item_score', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_receipt_items_tx', 'receipt_items', ['transaction_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_receipt_items_tx', table_name='receipt_items')
    op.drop_table('receipt_items')
