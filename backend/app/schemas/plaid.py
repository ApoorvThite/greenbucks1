from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


class PlaidItemCreate(BaseModel):
    user_id: int = Field(gt=0)
    item_id: str
    access_token: str
    institution_name: Optional[str] = None


class PlaidSyncResult(BaseModel):
    item_id: str
    transactions_upserted: int


class PublicTokenExchangeRequest(BaseModel):
    user_id: int = Field(gt=0)
    public_token: str
    institution_name: Optional[str] = None
