from __future__ import annotations

from datetime import date
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Header, status
from sqlalchemy import and_, desc, asc
from sqlalchemy.orm import Session
from uuid import uuid4
import csv
from io import StringIO, TextIOWrapper
from datetime import datetime, timedelta

from ...db.session import get_db
from ...models.plaid import Transaction
from ...models.user import User
from ...models.user import User
from ...core.security import hash_password
from ...core.security import decode_access_token
from ...schemas.transaction import TransactionRead, TransactionIngestRequest
from ...services.eco_scoring import (
    is_mixed_merchant,
    quick_merchant_score,
    compute_cashback,
    score_from_co2e_per_dollar,
)
from ...services.integrations.climatiq_client import estimate_item_footprint
import inspect

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=List[TransactionRead])
def list_transactions(
    user_id: int = Query(..., gt=0),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    merchant: Optional[str] = Query(None, description="Substring match on merchant name"),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    category: Optional[str] = Query(None, description="Keyword to match in name or merchant as a proxy for category"),
    sort_by: str = Query("date", pattern="^(date|amount|name)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction).filter(Transaction.user_id == user_id)

    if start_date is not None:
        q = q.filter(Transaction.date >= start_date)
    if end_date is not None:
        q = q.filter(Transaction.date <= end_date)
    if merchant:
        q = q.filter(Transaction.merchant_name.ilike(f"%{merchant}%"))
    if min_amount is not None:
        q = q.filter(Transaction.amount >= min_amount)
    if max_amount is not None:
        q = q.filter(Transaction.amount <= max_amount)
    if category:
        # Portable proxy: match keyword in transaction name or merchant
        like = f"%{category}%"
        q = q.filter((Transaction.name.ilike(like)) | (Transaction.merchant_name.ilike(like)))

    # Sorting
    sort_column = {
        "date": Transaction.date,
        "amount": Transaction.amount,
        "name": Transaction.name,
    }[sort_by]
    order = desc if sort_dir == "desc" else asc
    q = q.order_by(order(sort_column), order(Transaction.id)).offset(offset).limit(limit)
    results = q.all()
    return results


# --- Auth helpers ---
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


@router.get("/my", response_model=List[TransactionRead])
def list_my_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    merchant: Optional[str] = Query(None, description="Substring match on merchant name"),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    category: Optional[str] = Query(None, description="Keyword to match in name or merchant as a proxy for category"),
    sort_by: str = Query("date", pattern="^(date|amount|name)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Transaction).filter(Transaction.user_id == current_user.id)

    if start_date is not None:
        q = q.filter(Transaction.date >= start_date)
    if end_date is not None:
        q = q.filter(Transaction.date <= end_date)
    if merchant:
        q = q.filter(Transaction.merchant_name.ilike(f"%{merchant}%"))
    if min_amount is not None:
        q = q.filter(Transaction.amount >= min_amount)
    if max_amount is not None:
        q = q.filter(Transaction.amount <= max_amount)
    if category:
        like = f"%{category}%"
        q = q.filter((Transaction.name.ilike(like)) | (Transaction.merchant_name.ilike(like)))

    sort_column = {
        "date": Transaction.date,
        "amount": Transaction.amount,
        "name": Transaction.name,
    }[sort_by]
    order = desc if sort_dir == "desc" else asc
    q = q.order_by(order(sort_column), order(Transaction.id)).offset(offset).limit(limit)
    return q.all()


@router.post("/ingest", response_model=dict)
async def ingest_transactions(payload: TransactionIngestRequest, db: Session = Depends(get_db)):
    """Bulk insert hardcoded transactions for testing purposes.

    If an incoming transaction is missing `external_id`, one will be generated.
    Existing transactions (matched by `external_id`) will be updated.
    """
    created, updated = 0, 0
    for t in payload.transactions:
        ext_id = t.external_id or f"seed-{uuid4()}"
        existing = db.query(Transaction).filter(Transaction.external_id == ext_id).first()
        if existing:
            existing.user_id = payload.user_id
            existing.account_id = "Capital One"
            existing.date = t.date
            existing.name = t.name
            existing.merchant_name = t.merchant_name
            existing.amount = t.amount
            existing.iso_currency_code = t.iso_currency_code
            existing.category = t.category
            existing.location = t.location
            # eco/cashback
            if is_mixed_merchant(existing.merchant_name):
                existing.needs_receipt = True
                existing.eco_score = None
                existing.cashback_usd = compute_cashback(existing.amount, None)
            else:
                # Compute eco using Climatiq (live if enabled) for the whole transaction amount
                try:
                    est = estimate_item_footprint(existing.merchant_name or existing.name, float(existing.amount), 1, existing.category)
                    res = await est if inspect.isawaitable(est) else est
                    if isinstance(res, tuple) and len(res) == 3:
                        kg_co2e, _src, _fid = res
                    else:
                        kg_co2e = res
                    amt = float(existing.amount) if existing.amount else 0.0
                    co2_per_usd = (float(kg_co2e) / amt) if amt > 0 else float(kg_co2e)
                    score = score_from_co2e_per_dollar(co2_per_usd)
                    eco_bonus_rate = (Decimal(score) / Decimal(10)) * Decimal("0.04")
                    base_cashback_rate = Decimal("0.01")
                    total_rate = base_cashback_rate + eco_bonus_rate
                    existing.eco_score = score
                    existing.needs_receipt = False
                    existing.cashback_usd = (Decimal(str(existing.amount)) * total_rate).quantize(Decimal("0.01"))
                except Exception:
                    # Fallback to legacy quick score path
                    score = quick_merchant_score(existing.merchant_name, existing.category)
                    existing.eco_score = score
                    existing.needs_receipt = False
                    existing.cashback_usd = compute_cashback(existing.amount, score)
            db.add(existing)
            updated += 1
        else:
            # eco/cashback
            if is_mixed_merchant(t.merchant_name):
                eco_score = None
                needs_receipt = True
                cashback = compute_cashback(t.amount, None)
            else:
                # Compute eco for non-mixed: live Climatiq when available; fallback to quick score
                try:
                    est = estimate_item_footprint(t.merchant_name or t.name, float(t.amount), 1, t.category)
                    res = await est if inspect.isawaitable(est) else est
                    if isinstance(res, tuple) and len(res) == 3:
                        kg_co2e, _src, _fid = res
                    else:
                        kg_co2e = res
                    amt = float(t.amount) if t.amount else 0.0
                    co2_per_usd = (float(kg_co2e) / amt) if amt > 0 else float(kg_co2e)
                    eco_score = score_from_co2e_per_dollar(co2_per_usd)
                    eco_bonus_rate = (Decimal(eco_score) / Decimal(10)) * Decimal("0.04")
                    base_cashback_rate = Decimal("0.01")
                    total_rate = base_cashback_rate + eco_bonus_rate
                    needs_receipt = False
                    cashback = (Decimal(str(t.amount)) * total_rate).quantize(Decimal("0.01"))
                except Exception:
                    eco_score = quick_merchant_score(t.merchant_name, t.category)
                    needs_receipt = False
                    cashback = compute_cashback(t.amount, eco_score)

            db.add(Transaction(
                user_id=payload.user_id,
                plaid_item_id=None,
                external_id=ext_id,
                account_id="Capital One",
                date=t.date,
                name=t.name,
                merchant_name=t.merchant_name,
                amount=t.amount,
                iso_currency_code=t.iso_currency_code,
                category=t.category,
                location=t.location,
                eco_score=eco_score,
                cashback_usd=cashback,
                needs_receipt=needs_receipt,
            ))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}


@router.post("/seed_rich", response_model=dict)
def seed_rich_dataset(
    number_of_users: int = Form(3, ge=1, le=20),
    days: int = Form(30, ge=7, le=180),
    email_prefix: str = Form("seed_user"),
    db: Session = Depends(get_db),
):
    """Generate multi-user synthetic data aligned with eco categories.

    Creates users if missing: {email_prefix}+<n>@example.com for n in [1..N].
    For each user, generates transactions over the last `days` days across:
    - Green: public transit, biking, EV charging, organic groceries, local markets.
    - Neutral: utilities, pharmacies, general retail.
    - Impact: gasoline, flights, ride-share, fast food.
    """
    today = datetime.utcnow().date()
    start = today - timedelta(days=days)

    # Ensure users exist
    users: list[User] = []
    for i in range(1, number_of_users + 1):
        email = f"{email_prefix}+{i}@example.com"
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(email=email, hashed_password=hash_password("password123"), full_name=f"Seed User {i}")
            db.add(u)
            db.flush()  # get ID
        users.append(u)
    db.commit()

    # Category templates (merchant, base_name, base_amt, cat)
    green = [
        ("CATA Bus", "Public Transit", 2.75, ["Travel", "Public Transit"]),
        ("EVgo", "EV Charging", 8.50, ["Auto", "Electric Charging"]),
        ("Local Farmers Market", "Organic Produce", 22.0, ["Shops", "Groceries", "Organic"]),
        ("REI", "Bike Accessories", 18.0, ["Shops", "Sports"]),
        ("Goodwill", "Second-hand", 12.0, ["Shops", "Thrift"]),
    ]
    neutral = [
        ("Walgreens", "Pharmacy", 14.0, ["Health", "Pharmacy"]),
        ("Target", "Household", 28.0, ["Shops", "Retail"]),
        ("PG&E", "Utilities", 65.0, ["Bills", "Utilities"]),
        ("Apple", "Apps", 4.99, ["Digital", "Apps"]),
    ]
    impact = [
        ("Shell", "Gasoline", 42.0, ["Auto", "Gas"]),
        ("United Airlines", "Flight", 280.0, ["Travel", "Air"]),
        ("Uber", "Ride", 13.0, ["Travel", "Ride Share"]),
        ("McDonald's", "Fast Food", 9.0, ["Food", "Fast Food"]),
    ]

    created = 0
    for u in users:
        for d in range(days):
            tx_date = start + timedelta(days=d + 1)
            # pattern: more green on weekdays, more impact on weekends
            is_weekend = tx_date.weekday() >= 5
            day_set = ([] if is_weekend else green[:3]) + neutral[:2] + (impact[:2] if is_weekend else impact[:1])
            # slight variation across users
            rotate = (u.id + d) % len(day_set)
            day_tx = day_set[rotate:] + day_set[:rotate]
            # 2-4 transactions
            for j, (merchant, base_name, base_amt, cats) in enumerate(day_tx[: 2 + (d % 3) - (1 if is_weekend else 0) ]):
                amt = round(base_amt * (0.8 + ((j + u.id % 3) * 0.12)), 2)
                ext_id = f"rich-{u.id}-{tx_date.isoformat()}-{j}-{merchant.replace(' ', '')}"
                if db.query(Transaction).filter(Transaction.external_id == ext_id).first():
                    continue
                db.add(Transaction(
                    user_id=u.id,
                    plaid_item_id=None,
                    external_id=ext_id,
                    account_id="demo-account",
                    date=tx_date,
                    name=f"{merchant} {base_name}",
                    merchant_name=merchant,
                    amount=amt,
                    iso_currency_code="USD",
                    category=cats,
                    location=None,
                ))
                created += 1
    db.commit()
    return {"users": len(users), "days": days, "created": created}


@router.post("/seed_demo", response_model=dict)
def seed_demo_data(user_id: int = Form(..., gt=0), db: Session = Depends(get_db)):
    """Generate a month of sample data across grocery, transport, and eating-out.

    This helps test eco scoring and leaderboards without Plaid.
    """
    today = datetime.utcnow().date()
    start = today - timedelta(days=30)

    categories = [
        # (merchant, name, base_amount, category list)
        ("Whole Foods", "Groceries", 45.0, ["Shops", "Groceries"]),
        ("Trader Joe's", "Groceries", 32.0, ["Shops", "Groceries"]),
        ("Safeway", "Groceries", 28.0, ["Shops", "Groceries"]),
        ("Uber", "Ride", 14.0, ["Travel", "Ride Share"]),
        ("Lyft", "Ride", 13.0, ["Travel", "Ride Share"]),
        ("Blue Bottle", "Coffee", 6.0, ["Food and Drink", "Coffee Shop"]),
        ("Starbucks", "Coffee", 5.0, ["Food and Drink", "Coffee Shop"]),
        ("Chipotle", "Lunch", 11.0, ["Food and Drink", "Fast Food"]),
        ("Sweetgreen", "Salad", 13.0, ["Food and Drink", "Restaurant"]),
        ("CATA Bus", "Bus Pass", 2.75, ["Travel", "Public Transit"]),
    ]

    created = 0
    for i in range(1, 31):
        tx_date = start + timedelta(days=i)
        # 2-4 transactions per day
        daily = categories[(i % len(categories)):] + categories[:(i % len(categories))]
        for j, (merchant, base_name, base_amt, cats) in enumerate(daily[: 2 + (i % 3)]):
            amt = round(base_amt * (0.8 + (j * 0.1)), 2)
            ext_id = f"seed-{user_id}-{tx_date.isoformat()}-{j}"
            exists = db.query(Transaction).filter(Transaction.external_id == ext_id).first()
            if exists:
                continue
            # determine eco/cashback
            if is_mixed_merchant(merchant):
                eco_score = None
                needs_receipt = True
                cashback = compute_cashback(amt, None)
            else:
                eco_score = quick_merchant_score(merchant, cats)
                needs_receipt = False
                cashback = compute_cashback(amt, eco_score)

            db.add(Transaction(
                user_id=user_id,
                plaid_item_id=None,
                external_id=ext_id,
                account_id="Capital One",
                date=tx_date,
                name=f"{merchant} {base_name}",
                merchant_name=merchant,
                amount=amt,
                iso_currency_code="USD",
                category=cats,
                location=None,
                eco_score=eco_score,
                cashback_usd=cashback,
                needs_receipt=needs_receipt,
            ))
            created += 1
    db.commit()
    return {"created": created}


@router.post("/recompute_all", response_model=dict)
async def recompute_all(
    user_id: int | None = None,
    only_missing: bool = True,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Backfill eco_score and cashback_usd for existing transactions.

    - Mixed merchants remain needs_receipt=True and are skipped.
    - Non-mixed merchants: compute kgCO2e via Climatiq (if enabled) on full transaction amount,
      map to eco_score, then compute cashback as base 1% + up to 4% bonus.
    """
    q = db.query(Transaction)
    if user_id is not None:
        q = q.filter(Transaction.user_id == user_id)
    # Process the most recent transactions first
    q = q.order_by(desc(Transaction.date), desc(Transaction.id)).limit(max(1, min(limit, 1000)))
    rows = q.all()
    updated = 0
    for tx in rows:
        try:
            if is_mixed_merchant(tx.merchant_name):
                # Mixed: require receipt, leave until upload
                tx.needs_receipt = True
                if not only_missing:
                    tx.eco_score = None
                    tx.cashback_usd = None
                db.add(tx)
                updated += 1
                continue

            # Skip if only_missing and already has values
            if only_missing and (tx.eco_score is not None and tx.cashback_usd is not None):
                continue

            est = estimate_item_footprint(tx.merchant_name or tx.name, float(tx.amount), 1, tx.category)
            res = await est if inspect.isawaitable(est) else est
            if isinstance(res, tuple) and len(res) == 3:
                kg_co2e, _src, _fid = res
            else:
                kg_co2e = res
            amt = float(tx.amount) if tx.amount else 0.0
            co2_per_usd = (float(kg_co2e) / amt) if amt > 0 else float(kg_co2e)
            score = score_from_co2e_per_dollar(co2_per_usd)
            eco_bonus_rate = (Decimal(score) / Decimal(10)) * Decimal("0.04")
            base_cashback_rate = Decimal("0.01")
            total_rate = base_cashback_rate + eco_bonus_rate
            tx.eco_score = score
            tx.needs_receipt = False
            tx.cashback_usd = (Decimal(str(tx.amount)) * total_rate).quantize(Decimal("0.01"))
            db.add(tx)
            updated += 1
        except Exception:
            # Fallback: compute quick score and cashback with the same rate formula
            try:
                score = quick_merchant_score(tx.merchant_name, tx.category)
                eco_bonus_rate = (Decimal(score) / Decimal(10)) * Decimal("0.04")
                base_cashback_rate = Decimal("0.01")
                total_rate = base_cashback_rate + eco_bonus_rate
                tx.eco_score = score
                tx.needs_receipt = False
                tx.cashback_usd = (Decimal(str(tx.amount)) * total_rate).quantize(Decimal("0.01"))
                db.add(tx)
                updated += 1
            except Exception:
                # If even fallback fails, leave as-is
                continue
    db.commit()
    return {"processed": len(rows), "updated": updated}


@router.post("/upload_csv", response_model=dict)
async def upload_csv(
    user_id: int = Form(..., gt=0),
    file: UploadFile = File(..., description="CSV with headers: date,name,merchant_name,amount,external_id(optional),account_id(optional),iso_currency_code(optional),category(optional comma/pipe-separated)"),
    db: Session = Depends(get_db),
):
    """Ingest transactions from an uploaded CSV file.

    Required columns: date (YYYY-MM-DD), name, amount
    Optional: merchant_name, external_id, account_id, iso_currency_code, category, location_* fields
    """
    contents = await file.read()
    text = contents.decode("utf-8", errors="replace")
    reader = csv.DictReader(StringIO(text))

    created, updated = 0, 0
    for row in reader:
        # Normalize fields
        ext_id = row.get("external_id") or f"csv-{uuid4()}"
        try:
            tx_date = datetime.strptime((row.get("date") or "").strip(), "%Y-%m-%d").date()
        except Exception:
            # skip invalid row
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        merchant = (row.get("merchant_name") or "").strip() or None
        try:
            amount = float((row.get("amount") or "0").strip())
        except Exception:
            amount = 0.0
        iso = (row.get("iso_currency_code") or "USD").strip() or "USD"

        cat_raw = row.get("category") or ""
        if "|" in cat_raw:
            cats = [c.strip() for c in cat_raw.split("|") if c.strip()]
        else:
            cats = [c.strip() for c in cat_raw.split(",") if c.strip()]
        cats = cats or None

        # Location fields (optional)
        loc = {}
        for key in ["location_city", "location_state", "location_country", "location_lat", "location_lon"]:
            val = row.get(key)
            if val is not None and str(val).strip() != "":
                loc[key.replace("location_", "")] = val
        if not loc:
            loc = None

        existing = db.query(Transaction).filter(Transaction.external_id == ext_id).first()
        if existing:
            existing.user_id = user_id
            existing.account_id = "Capital One"
            existing.date = tx_date
            existing.name = name
            existing.merchant_name = merchant
            existing.amount = amount
            existing.iso_currency_code = iso
            existing.category = cats
            existing.location = loc
            # eco/cashback
            if is_mixed_merchant(existing.merchant_name):
                existing.needs_receipt = True
                existing.eco_score = None
                existing.cashback_usd = compute_cashback(existing.amount, None)
            else:
                try:
                    est = estimate_item_footprint(existing.merchant_name or existing.name, float(existing.amount), 1)
                    res = await est if inspect.isawaitable(est) else est
                    if isinstance(res, tuple) and len(res) == 3:
                        kg_co2e, _src, _fid = res
                    else:
                        kg_co2e = res
                    amt = float(existing.amount) if existing.amount else 0.0
                    co2_per_usd = (float(kg_co2e) / amt) if amt > 0 else float(kg_co2e)
                    score = score_from_co2e_per_dollar(co2_per_usd)
                    eco_bonus_rate = (Decimal(score) / Decimal(10)) * Decimal("0.04")
                    base_cashback_rate = Decimal("0.01")
                    total_rate = base_cashback_rate + eco_bonus_rate
                    existing.eco_score = score
                    existing.needs_receipt = False
                    existing.cashback_usd = (Decimal(str(existing.amount)) * total_rate).quantize(Decimal("0.01"))
                except Exception:
                    score = quick_merchant_score(existing.merchant_name, existing.category)
                    existing.eco_score = score
                    existing.needs_receipt = False
                    existing.cashback_usd = compute_cashback(existing.amount, score)
            db.add(existing)
            updated += 1
        else:
            if is_mixed_merchant(merchant):
                eco_score = None
                needs_receipt = True
                cashback = compute_cashback(amount, None)
            else:
                try:
                    est = estimate_item_footprint(merchant or name, float(amount), 1, cats)
                    res = await est if inspect.isawaitable(est) else est
                    if isinstance(res, tuple) and len(res) == 3:
                        kg_co2e, _src, _fid = res
                    else:
                        kg_co2e = res
                    amt = float(amount) if amount else 0.0
                    co2_per_usd = (float(kg_co2e) / amt) if amt > 0 else float(kg_co2e)
                    eco_score = score_from_co2e_per_dollar(co2_per_usd)
                    eco_bonus_rate = (Decimal(eco_score) / Decimal(10)) * Decimal("0.04")
                    base_cashback_rate = Decimal("0.01")
                    total_rate = base_cashback_rate + eco_bonus_rate
                    needs_receipt = False
                    cashback = (Decimal(str(amount)) * total_rate).quantize(Decimal("0.01"))
                except Exception:
                    eco_score = quick_merchant_score(merchant, cats)
                    needs_receipt = False
                    cashback = compute_cashback(amount, eco_score)

            db.add(Transaction(
                user_id=user_id,
                plaid_item_id=None,
                external_id=ext_id,
                account_id="Capital One",
                date=tx_date,
                name=name,
                merchant_name=merchant,
                amount=amount,
                iso_currency_code=iso,
                category=cats,
                location=loc,
                eco_score=eco_score,
                cashback_usd=cashback,
                needs_receipt=needs_receipt,
            ))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}
