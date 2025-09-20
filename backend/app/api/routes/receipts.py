from __future__ import annotations

from typing import List, Optional
import inspect
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.plaid import Transaction
from ...models.receipt import ReceiptItem
from ...models.user import User
from ...core.security import decode_access_token
from ...services.integrations.ocr_google_vision import (
    parse_receipt,
    parse_receipt_diagnostics,
    extract_text,
    get_local_ocr_text,
)
from ...services.integrations.cerebras_client import parse_items_with_cerebras
from ...services.integrations.climatiq_client import estimate_item_footprint
from ...services.eco_scoring import score_from_co2e_per_dollar, compute_cashback

router = APIRouter(prefix="/receipts", tags=["receipts"])


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    sub = payload.get("sub") or {}
    user_id = sub.get("id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user: User | None = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.post("/upload", response_model=dict)
async def upload_receipt(
    transaction_id: int = Form(..., gt=0),
    file: UploadFile = File(...),
    debug_raw_text: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tx: Transaction | None = db.query(Transaction).filter(Transaction.id == transaction_id, Transaction.user_id == current_user.id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found for user")

    # Read file bytes
    content = await file.read()
    items, ocr_flow = await parse_receipt_diagnostics(content)
    raw_text = ""
    ocr_diagnostics = {}
    if debug_raw_text:
        raw_text, ocr_diagnostics = await extract_text(content)
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
        # Estimate footprint (new signature may return a tuple)
        est = estimate_item_footprint(name, price, qty)
        res = await est if inspect.isawaitable(est) else est
        if isinstance(res, tuple) and len(res) == 3:
            kg, climatiq_source, climatiq_factor_id = res
        else:
            kg, climatiq_source, climatiq_factor_id = res, "fallback", None
        # Compute item score using kgCO2e per dollar if price available; otherwise fallback to 5
        if price and price > 0:
            co2_per_usd = float(kg) / float(price)
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

    # Build detailed items list from DB (including kg_co2e and item_score)
    stored = db.query(ReceiptItem).filter(ReceiptItem.transaction_id == tx.id).all()
    # We don't persist diagnostics on the model; rerun a lightweight mapping for response enrichment
    items_detailed = []
    for r in stored:
        items_detailed.append({
            "name": r.name,
            "price": str(r.price) if r.price is not None else None,
            "qty": r.qty,
            "kg_co2e": str(r.kg_co2e) if r.kg_co2e is not None else None,
            "item_score": r.item_score,
            # best-effort: indicate likely source based on USE_REAL_CLIMATIQ flag
            "climatiq_source": "live" if r.kg_co2e is not None else "fallback",
            "climatiq_factor_id": None,
        })

    # Compute eco bonus rate from item scores and base amount from subtotal of parsed items
    try:
        subtotal = sum(Decimal(str(it.get("price") or 0)) for it in items)
    except Exception:
        subtotal = Decimal("0")
    try:
        sum_scores = sum((r.get("item_score") or 5) for r in items_detailed) if items_detailed else 0
        max_scores = max(1, len(items_detailed) * 10)
        eco_bonus_rate = float(sum_scores) / float(max_scores) * 0.04  # 0%..4%
    except Exception:
        eco_bonus_rate = 0.0
    base_cashback_rate = 0.01
    total_rate = base_cashback_rate + eco_bonus_rate
    eco_bonus_amount = subtotal * Decimal(str(total_rate))
    resp = {
        "transaction_id": tx.id,
        "eco_score": tx.eco_score,
        "cashback_usd": str(eco_bonus_amount),
        "items": len(items),
        "parsed_items": items,
        "eco_breakdown": {
            "base_cashback_rate": base_cashback_rate,
            "eco_bonus_rate": eco_bonus_rate,
            "total_rate": total_rate,
            "base_amount": str(subtotal),
            "eco_bonus_amount": str(eco_bonus_amount),
        },
        "parser_used": ocr_flow.get("parser_used"),
        "text_source": ocr_flow.get("text_source"),
        "items_detailed": items_detailed,
    }
    if debug_raw_text:
        # Include local OCR text to help debug prices if Vision fails
        local_text = ""
        try:
            local_text = get_local_ocr_text(content)
        except Exception:
            local_text = ""
        resp["raw_text"] = raw_text if raw_text else [raw_text, ocr_diagnostics, {"local_text": local_text[:2000] if local_text else ""}]
    return resp


class ReceiptText(BaseModel):
    text: str
    transaction_id: int | None = None


@router.post("/parse_text", response_model=dict)
async def parse_receipt_text_debug(payload: ReceiptText):
    """Debug endpoint: run Cerebras parser directly on provided text.

    Returns items array and echoes model used. This bypasses OCR so we can validate
    that the LLM extracts the correct name/price pairs from clean text.
    """
    items = parse_items_with_cerebras(payload.text)
    return {
        "model": "cerebras",
        "items": items,
        "count": len(items),
    }


@router.post("/ingest_text", response_model=dict)
async def ingest_receipt_text(payload: ReceiptText, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Use Cerebras to parse provided receipt text and persist items to a transaction.

    This bypasses OCR. Requires user_id and transaction_id. Returns the same response
    structure as /receipts/upload.
    """
    if not payload.transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id is required")

    tx: Transaction | None = (
        db.query(Transaction)
        .filter(Transaction.id == payload.transaction_id, Transaction.user_id == current_user.id)
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found for user")

    items = parse_items_with_cerebras(payload.text or "")
    if not items:
        raise HTTPException(status_code=400, detail="Could not parse items from text")

    # Clear previous items
    db.query(ReceiptItem).filter(ReceiptItem.transaction_id == tx.id).delete(synchronize_session=False)

    total_price = Decimal("0")
    for it in items:
        name = it.get("name")
        price = it.get("price")
        qty = it.get("qty")
        if not name or price is None:
            continue
        price_dec = Decimal(str(round(float(price), 2)))
        total_price += price_dec
        # Estimate footprint and score (with diagnostics)
        est = estimate_item_footprint(name, price_dec, qty or 1)
        res = await est if inspect.isawaitable(est) else est
        if isinstance(res, tuple) and len(res) == 3:
            kg_co2e, climatiq_source, climatiq_factor_id = res
        else:
            kg_co2e, climatiq_source, climatiq_factor_id = res, "fallback", None
        co2e_per_dollar = float(kg_co2e) / float(price_dec) if float(price_dec) > 0 else float(kg_co2e)
        item_score = score_from_co2e_per_dollar(co2e_per_dollar)
        row = ReceiptItem(
            transaction_id=tx.id,
            name=name,
            price=price_dec,
            qty=qty,
            kg_co2e=kg_co2e,
            item_score=item_score,
        )
        db.add(row)

    # Compute transaction eco_score weighted by price
    db.flush()
    stored = db.query(ReceiptItem).filter(ReceiptItem.transaction_id == tx.id).all()
    if stored:
        # weighted average by price
        numerator = sum((r.item_score or 5) * float(r.price or 0) for r in stored)
        denom = sum(float(r.price or 0) for r in stored) or 1.0
        tx_score = int(round(numerator / denom))
    else:
        tx_score = 5

    tx.eco_score = max(0, min(10, tx_score))
    tx.needs_receipt = False
    # New cashback/eco bonus logic based on item scores and subtotal
    subtotal = sum((r.price or Decimal("0")) for r in stored) if stored else Decimal("0")
    sum_scores = sum((r.item_score or 5) for r in stored) if stored else 0
    max_scores = max(1, len(stored) * 10)
    eco_bonus_rate = float(sum_scores) / float(max_scores) * 0.04  # 0%..4%
    base_cashback_rate = 0.01
    total_rate = base_cashback_rate + eco_bonus_rate
    tx.cashback_usd = subtotal * Decimal(str(total_rate))
    db.add(tx)
    db.commit()

    items_detailed = [
        {
            "name": r.name,
            "price": str(r.price) if r.price is not None else None,
            "qty": r.qty,
            "kg_co2e": str(r.kg_co2e) if r.kg_co2e is not None else None,
            "item_score": r.item_score,
        }
        for r in stored
    ]

    return {
        "transaction_id": tx.id,
        "eco_score": tx.eco_score,
        "cashback_usd": str(tx.cashback_usd),
        "items": len(items),
        "parsed_items": items,
        "eco_breakdown": {
            "base_cashback_rate": base_cashback_rate,
            "eco_bonus_rate": eco_bonus_rate,
            "total_rate": total_rate,
            "base_amount": str(subtotal),
            "eco_bonus_amount": str(tx.cashback_usd),
        },
        "parser_used": "cerebras",
        "text_source": "provided_text",
        "items_detailed": items_detailed,
    }
@router.get("/{transaction_id}/items", response_model=list[dict])
def list_receipt_items(transaction_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetch stored parsed receipt items for a user's transaction."""
    tx: Transaction | None = db.query(Transaction).filter(Transaction.id == transaction_id, Transaction.user_id == current_user.id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found for user")
    rows = db.query(ReceiptItem).filter(ReceiptItem.transaction_id == transaction_id).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "price": str(r.price) if r.price is not None else None,
            "qty": r.qty,
            "kg_co2e": str(r.kg_co2e) if r.kg_co2e is not None else None,
            "item_score": r.item_score,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
