"""add eco fields to transactions

Revision ID: 20250920_024700
Revises: 20250920_001300
Create Date: 2025-09-20 02:47:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20250920_024700'
down_revision: str | None = '20250920_001300'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('eco_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cashback_usd', sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column('needs_receipt', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('needs_receipt')
        batch_op.drop_column('cashback_usd')
        batch_op.drop_column('eco_score')
