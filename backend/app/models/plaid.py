from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    JSON,
    UniqueConstraint,
    Index,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base


class PlaidItem(Base):
    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    # Plaid identifiers
    item_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    institution_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Encrypted access token
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_transactions_external_id"),
        Index("ix_transactions_user_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    plaid_item_id: Mapped[int | None] = mapped_column(ForeignKey("plaid_items.id", ondelete="SET NULL"), index=True)

    # External identifiers
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)  # Plaid transaction_id
    account_id: Mapped[Optional[str]] = mapped_column(String(128))  # Plaid account_id

    # Core fields
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    iso_currency_code: Mapped[Optional[str]] = mapped_column(String(3))

    # Optional metadata
    category: Mapped[Optional[list[str]]] = mapped_column(JSON)
    location: Mapped[Optional[dict]] = mapped_column(JSON)

    # Eco/cashback fields
    # eco_score in 0..10, nullable until computed (esp. for mixed retailers needing receipt OCR)
    eco_score: Mapped[Optional[int]] = mapped_column(Integer)
    cashback_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    needs_receipt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
