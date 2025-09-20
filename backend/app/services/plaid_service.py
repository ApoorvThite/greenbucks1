from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from plaid.configuration import Configuration
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_response import TransactionsSyncResponse
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

from ..core.config import get_settings
from ..core.crypto import encrypt_to_bytes, decrypt_to_str
from ..models.plaid import PlaidItem, Transaction


def _plaid_client() -> plaid_api.PlaidApi:
    settings = get_settings()
    env = (settings.plaid_env or "sandbox").lower()
    host_map = {
        "sandbox": "https://sandbox.plaid.com",
        "development": "https://development.plaid.com",
        "production": "https://production.plaid.com",
    }
    host = host_map.get(env, host_map["sandbox"])

    config = Configuration(host=host, api_key={'clientId': settings.plaid_client_id, 'secret': settings.plaid_secret})
    api_client = plaid_api.ApiClient(config)
    return plaid_api.PlaidApi(api_client)


def exchange_public_token(public_token: str) -> tuple[str, str]:
    """Exchange a Link public_token for an access_token and item_id.

    Returns (item_id, access_token).
    """
    client = _plaid_client()
    req = ItemPublicTokenExchangeRequest(public_token=public_token)
    resp = client.item_public_token_exchange(req)
    # resp has access_token and item_id
    return resp.item_id, resp.access_token


def store_access_token(db: Session, *, user_id: int, item_id: str, access_token: str, institution_name: Optional[str] = None) -> PlaidItem:
    encrypted = encrypt_to_bytes(access_token)
    existing = db.query(PlaidItem).filter(PlaidItem.item_id == item_id).first()
    if existing:
        existing.access_token_encrypted = encrypted
        if institution_name is not None:
            existing.institution_name = institution_name
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = PlaidItem(
        user_id=user_id,
        item_id=item_id,
        institution_name=institution_name,
        access_token_encrypted=encrypted,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except Exception:
            pass
    # Fallback to today if missing/invalid (shouldn't happen in Plaid)
    return date.today()


def _upsert_transactions(db: Session, *, user_id: int, plaid_item_id: Optional[int], txns: Iterable[dict]) -> int:
    count = 0
    for t in txns:
        external_id = t.get("transaction_id")
        if not external_id:
            continue
        existing = db.query(Transaction).filter(Transaction.external_id == external_id).first()
        amount_raw = t.get("amount", 0)
        amount = Decimal(str(amount_raw if amount_raw is not None else 0))
        if existing:
            existing.name = t.get("name") or existing.name
            existing.merchant_name = t.get("merchant_name")
            existing.amount = amount
            existing.iso_currency_code = t.get("iso_currency_code")
            existing.category = t.get("category")
            existing.location = t.get("location")
            db.add(existing)
        else:
            db.add(Transaction(
                user_id=user_id,
                plaid_item_id=plaid_item_id,
                external_id=external_id,
                account_id=t.get("account_id"),
                date=_coerce_date(t.get("date")),
                name=t.get("name") or "",
                merchant_name=t.get("merchant_name"),
                amount=amount,
                iso_currency_code=t.get("iso_currency_code"),
                category=t.get("category"),
                location=t.get("location"),
            ))
        count += 1
    db.commit()
    return count


def fetch_and_store_transactions(db: Session, *, plaid_item: PlaidItem, start_date: Optional[date] = None, end_date: Optional[date] = None) -> int:
    """Fetch transactions via Plaid Transactions Sync and upsert into DB.

    Returns number of transactions upserted.
    """
    client = _plaid_client()
    access_token = decrypt_to_str(plaid_item.access_token_encrypted)

    # Use transactions/sync to pull incremental changes
    next_cursor: Optional[str] = None
    total = 0
    while True:
        req_kwargs: dict = {
            "access_token": access_token,
            "count": 500,
        }
        if next_cursor is not None:
            req_kwargs["cursor"] = next_cursor
        req = TransactionsSyncRequest(**req_kwargs)
        resp: TransactionsSyncResponse = client.transactions_sync(req)
        added = [t.to_dict() for t in resp.added]
        modified = [t.to_dict() for t in resp.modified]
        removed = [t.to_dict() for t in resp.removed]

        total += _upsert_transactions(db, user_id=plaid_item.user_id, plaid_item_id=plaid_item.id, txns=added + modified)
        # Note: handle removed by soft-deleting in future if needed

        if resp.next_cursor:
            next_cursor = resp.next_cursor
        if not resp.has_more:
            break

    return total


def sync_all_items(db: Session) -> int:
    """Sync transactions for all Plaid items; returns total upserted."""
    total = 0
    items = db.query(PlaidItem).all()
    for it in items:
        total += fetch_and_store_transactions(db, plaid_item=it)
    return total


def sync_by_item_id(db: Session, item_id: str) -> int:
    item = db.query(PlaidItem).filter(PlaidItem.item_id == item_id).first()
    if not item:
        return 0
    return fetch_and_store_transactions(db, plaid_item=item)


def create_link_token(user_id: int) -> str:
    """Create a Link token for initializing Plaid Link on the frontend."""
    client = _plaid_client()
    settings = get_settings()
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        client_name=settings.app_name or "GreenBucks",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    resp = client.link_token_create(req)
    return resp.link_token


def sandbox_create_public_token(institution_id: str = "ins_109508", products: Optional[list[str]] = None) -> str:
    """Create a sandbox public_token for testing without running Link UI.

    Defaults to an institution_id that is commonly available in Plaid sandbox.
    """
    client = _plaid_client()
    if products is None:
        products = ["transactions"]
    req = SandboxPublicTokenCreateRequest(
        institution_id=institution_id,
        initial_products=[Products(p) for p in products],
    )
    resp = client.sandbox_public_token_create(req)
    return resp.public_token
