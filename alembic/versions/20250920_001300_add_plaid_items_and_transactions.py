"""add plaid_items and transactions tables

Revision ID: 20250920_001300
Revises: 20250919_234500
Create Date: 2025-09-20 00:13:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20250920_001300'
down_revision: str | None = '20250919_234500'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    # Create plaid_items table (with unique constraint inline) if it doesn't exist
    if 'plaid_items' not in existing_tables:
        op.create_table(
            'plaid_items',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('item_id', sa.String(length=128), nullable=False),
            sa.Column('institution_name', sa.String(length=255), nullable=True),
            sa.Column('access_token_encrypted', sa.LargeBinary(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('item_id', name='uq_plaid_items_item_id'),
        )
        op.create_index('ix_plaid_items_user_id', 'plaid_items', ['user_id'], unique=False)
    else:
        # Ensure unique constraint exists (SQLite requires batch operations)
        constraints = inspector.get_unique_constraints('plaid_items')
        has_unique = any(c['name'] == 'uq_plaid_items_item_id' for c in constraints)
        if not has_unique:
            with op.batch_alter_table('plaid_items') as batch_op:
                batch_op.create_unique_constraint('uq_plaid_items_item_id', ['item_id'])
        # Ensure index exists
        idx_names = {ix['name'] for ix in inspector.get_indexes('plaid_items')}
        if 'ix_plaid_items_user_id' not in idx_names:
            op.create_index('ix_plaid_items_user_id', 'plaid_items', ['user_id'], unique=False)

    # Create transactions table if it doesn't exist
    if 'transactions' not in existing_tables:
        op.create_table(
            'transactions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('plaid_item_id', sa.Integer(), sa.ForeignKey('plaid_items.id', ondelete='SET NULL'), nullable=True),
            sa.Column('external_id', sa.String(length=128), nullable=False),
            sa.Column('account_id', sa.String(length=128), nullable=True),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('name', sa.String(length=512), nullable=False),
            sa.Column('merchant_name', sa.String(length=255), nullable=True),
            sa.Column('amount', sa.Numeric(12, 2), nullable=False),
            sa.Column('iso_currency_code', sa.String(length=3), nullable=True),
            sa.Column('category', sa.JSON(), nullable=True),
            sa.Column('location', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('external_id', name='uq_transactions_external_id'),
        )
        op.create_index('ix_transactions_user_date', 'transactions', ['user_id', 'date'], unique=False)
        op.create_index('ix_transactions_user_id', 'transactions', ['user_id'], unique=False)
        op.create_index('ix_transactions_plaid_item_id', 'transactions', ['plaid_item_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_transactions_plaid_item_id', table_name='transactions')
    op.drop_index('ix_transactions_user_id', table_name='transactions')
    op.drop_index('ix_transactions_user_date', table_name='transactions')
    op.drop_table('transactions')

    op.drop_constraint('uq_plaid_items_item_id', 'plaid_items', type_='unique')
    op.drop_index('ix_plaid_items_user_id', table_name='plaid_items')
    op.drop_table('plaid_items')
