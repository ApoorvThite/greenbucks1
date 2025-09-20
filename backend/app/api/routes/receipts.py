from __future__ import annotations

from typing import List
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.plaid import Transaction
from ...models.receipt import ReceiptItem
from ...services.integrations.ocr_google_vision import parse_receipt
from ...services.integrations.climatiq_client import estimate_item_footprint
from ...services.eco_scoring import score_from_co2e_per_dollar, compute_cashback

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/upload", response_model=dict)
async def upload_receipt(
    user_id: int = Form(..., gt=0),
    transaction_id: int = Form(..., gt=0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    tx: Transaction | None = db.query(Transaction).filter(Transaction.id == transaction_id, Transaction.user_id == user_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found for user")

    # Read file bytes
    content = await file.read()
    items = await parse_receipt(content)
    if not items:
        raise HTTPException(status_code=400, detail="Could not parse receipt")

    # Clear any previous items if reprocessing
    db.query(ReceiptItem).filter(ReceiptItem.transaction_id == tx.id).delete(synchronize_session=False)

    total_price = Decimal("0")
    weighted_score_sum = Decimal("0")

    for it in items:
        name = it.get("name") or "Unknown"
        price = it.get("price")
        qty = it.get("qty")
        kg = await estimate_item_footprint(name, price, qty)
        # Compute item score using kgCO2e per dollar if price available; otherwise fallback to 5
        if price and price > 0:
            co2_per_usd = kg / float(price)
            item_score = score_from_co2e_per_dollar(co2_per_usd)
        else:
            item_score = 5
        db.add(ReceiptItem(
            transaction_id=tx.id,
            name=name,
            price=Decimal(str(price)) if price is not None else None,
            qty=qty,
            kg_co2e=Decimal(str(kg)),
            item_score=item_score,
        ))
        if price and price > 0:
            p = Decimal(str(price))
            total_price += p
            weighted_score_sum += p * Decimal(item_score)

    # Aggregate transaction score (price-weighted mean if prices exist; else avg of items)
    if total_price > 0:
        tx_score = int((weighted_score_sum / total_price).quantize(Decimal("1")))
    else:
        # average simple
        scores = [it.get("item_score") for it in db.query(ReceiptItem).filter(ReceiptItem.transaction_id == tx.id).all() if it.item_score is not None]
        tx_score = int(sum(scores) / len(scores)) if scores else 5

    tx.eco_score = max(0, min(10, tx_score))
    tx.needs_receipt = False
    tx.cashback_usd = compute_cashback(tx.amount, tx.eco_score)

    db.add(tx)
    db.commit()

    return {
        "transaction_id": tx.id,
        "eco_score": tx.eco_score,
        "cashback_usd": str(tx.cashback_usd),
        "items": len(items),
    }
