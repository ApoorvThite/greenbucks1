from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel


class TransactionRead(BaseModel):
    id: int
    user_id: int
    plaid_item_id: Optional[int] = None
    external_id: str
    account_id: Optional[str] = None
    date: date
    name: str
    merchant_name: Optional[str] = None
    amount: Decimal
    iso_currency_code: Optional[str] = None
    category: Optional[list[str]] = None
    location: Optional[dict] = None
    eco_score: Optional[int] = None
    cashback_usd: Optional[Decimal] = None
    needs_receipt: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    # external_id optional; will be generated if not provided
    external_id: Optional[str] = None
    account_id: Optional[str] = None
    date: date
    name: str
    merchant_name: Optional[str] = None
    amount: Decimal
    iso_currency_code: Optional[str] = None
    category: Optional[list[str]] = None
    location: Optional[dict] = None


class TransactionIngestRequest(BaseModel):
    user_id: int
    transactions: List[TransactionCreate]
