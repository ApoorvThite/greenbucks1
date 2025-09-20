from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Integer, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    qty: Mapped[Optional[int]] = mapped_column(Integer)

    kg_co2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    item_score: Mapped[Optional[int]] = mapped_column(Integer)  # 0..10 per item

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
