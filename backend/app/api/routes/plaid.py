from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...schemas.plaid import PlaidItemCreate, PlaidSyncResult, PublicTokenExchangeRequest
from ...services.plaid_service import (
    store_access_token,
    fetch_and_store_transactions,
    exchange_public_token,
    create_link_token,
    sandbox_create_public_token,
)
from ...models.plaid import PlaidItem

router = APIRouter(prefix="/plaid", tags=["plaid"])


@router.post("/items", response_model=dict)
def create_plaid_item(payload: PlaidItemCreate, db: Session = Depends(get_db)):
    """Store an encrypted Plaid access token for a user + item.

    This assumes you have already exchanged a public_token for an access_token on the client or elsewhere.
    """
    if not payload.access_token:
        raise HTTPException(status_code=400, detail="access_token is required")

    item = store_access_token(
        db,
        user_id=payload.user_id,
        item_id=payload.item_id,
        access_token=payload.access_token,
        institution_name=payload.institution_name,
    )
    return {"item_id": item.item_id, "user_id": item.user_id}


@router.post("/sync", response_model=PlaidSyncResult)
def sync_transactions(user_id: int, item_id: str | None = None, db: Session = Depends(get_db)):
    """Trigger a sync of transactions for a specific item or all items for a user.

    If item_id is provided, only that item is synced; otherwise, all items for the user are synced.
    """
    total = 0
    if item_id:
        item: PlaidItem | None = db.query(PlaidItem).filter(PlaidItem.item_id == item_id, PlaidItem.user_id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Plaid item not found")
        total += fetch_and_store_transactions(db, plaid_item=item)
        return PlaidSyncResult(item_id=item.item_id, transactions_upserted=total)

    # Sync all items for user
    items = db.query(PlaidItem).filter(PlaidItem.user_id == user_id).all()
    if not items:
        raise HTTPException(status_code=404, detail="No Plaid items found for user")
    last_item_id = None
    for it in items:
        last_item_id = it.item_id
        total += fetch_and_store_transactions(db, plaid_item=it)
    return PlaidSyncResult(item_id=last_item_id or "", transactions_upserted=total)


@router.post("/link_token", response_model=dict)
def create_link_token_endpoint(user_id: int):
    """Create a Link token for initializing Plaid Link on the frontend."""
    token = create_link_token(user_id)
    return {"link_token": token}


@router.post("/sandbox_public_token", response_model=dict)
def sandbox_public_token_endpoint():
    """Create a sandbox public_token for testing without running Link UI."""
    public_token = sandbox_create_public_token()
    return {"public_token": public_token}


@router.post("/exchange_public_token", response_model=dict)
def exchange_public_token_endpoint(payload: PublicTokenExchangeRequest, db: Session = Depends(get_db)):
    """Exchange a public_token for an access_token and store it securely.

    Returns the associated item_id and user_id.
    """
    if not payload.public_token:
        raise HTTPException(status_code=400, detail="public_token is required")

    item_id, access_token = exchange_public_token(payload.public_token)
    stored = store_access_token(
        db,
        user_id=payload.user_id,
        item_id=item_id,
        access_token=access_token,
        institution_name=payload.institution_name,
    )
    return {"item_id": stored.item_id, "user_id": stored.user_id}
