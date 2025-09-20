from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...services.plaid_service import sync_by_item_id

router = APIRouter(prefix="/plaid", tags=["plaid-webhook"])


@router.post("/webhook")
async def plaid_webhook(request: Request, db: Session = Depends(get_db)):
    """Minimal Plaid webhook handler.

    Expects a JSON body with at least `item_id`. For Plaid Transactions webhooks,
    this will trigger a sync for that item. Returns a simple status.
    """
    payload = await request.json()
    item_id = payload.get("item_id")
    if not item_id:
        # Return 200 to avoid Plaid retry storms, but note missing item
        return {"received": True, "action": "ignored", "reason": "missing item_id"}

    try:
        upserted = sync_by_item_id(db, item_id)
        return {"received": True, "action": "synced", "item_id": item_id, "transactions_upserted": upserted}
    except Exception as e:
        # Don't fail the webhook; log-like response
        return {"received": True, "action": "error", "item_id": item_id, "error": str(e)}
