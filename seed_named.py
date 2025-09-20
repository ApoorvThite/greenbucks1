import requests
from datetime import date, timedelta

BASE = "http://127.0.0.1:8000"
USERS = [
    ("apoorv@example.com", "Apoorv"),
    ("aarya@example.com", "Aarya"),
    ("modak@example.com", "Modak"),
    ("kartavya@example.com", "Kartavya"),
    ("nikhil@example.com", "Nikhil"),
]

CATALOG = [
    ("Starbucks", "Starbucks", 4.75, ["Food and Drink", "Coffee Shop"]),
    ("Target", "Target", 29.88, ["Shops", "Retail"]),
    ("Walmart", "Walmart", 63.18, ["Shops", "Retail", "Superstore"]),
    ("Whole Foods Market", "Whole Foods Market", 18.75, ["Shops", "Groceries"]),
    ("Amazon", "Amazon", 23.49, ["Shops", "Online"]),
    ("Lyft", "Lyft", 9.60, ["Travel", "Ride Share"]),
    ("Uber", "Uber", 11.75, ["Travel", "Ride Share"]),
    ("Shell", "Shell Gas", 34.00, ["Auto", "Gas"]),
    ("CATA", "CATA Bus Pass", 25.00, ["Travel", "Public Transit"]),
    ("Farmer’s Market Co-op", "Farmer’s Market Co-op", 12.40, ["Shops", "Groceries", "Organic", "Local"]),
    ("SEPTA", "SEPTA Transit", 2.50, ["Travel", "Public Transit"]),
    ("Costco", "Costco", 84.12, ["Shops", "Wholesale"]),
    ("H Mart", "H Mart", 21.30, ["Shops", "Groceries", "International"]),
    ("Uber Eats", "Uber Eats", 16.99, ["Food and Drink", "Delivery"]),
    ("MTA", "MTA Subway", 2.90, ["Travel", "Public Transit"]),
    ("Electric Utility", "Electric Utility", 55.00, ["Bills", "Utilities", "Electric"]),
    ("PG&E", "PG&E Electric Utility", 44.00, ["Bills", "Utilities", "Electric"]),
    ("City of Palo Alto Utilities", "City of Palo Alto Utilities", 52.00, ["Bills", "Utilities", "Electric"]),
    ("Local Bike Shop", "Local Bike Shop", 12.00, ["Shops", "Sports", "Bicycle"]),
    ("Amtrak", "Amtrak Transit Pass", 18.00, ["Travel", "Rail"]),
    ("Starbucks", "Starbucks", 5.25, ["Food and Drink", "Coffee Shop"]),
    ("Target", "Target", 9.99, ["Shops", "Retail"]),
    ("Walmart", "Walmart", 14.22, ["Shops", "Retail", "Superstore"]),
    ("Whole Foods Market", "Whole Foods Market", 27.60, ["Shops", "Groceries"]),
    ("Amazon", "Amazon", 47.80, ["Shops", "Online"]),
    ("Lyft", "Lyft", 18.40, ["Travel", "Ride Share"]),
    ("Uber", "Uber", 22.30, ["Travel", "Ride Share"]),
    ("Shell", "Shell Gas", 41.75, ["Auto", "Gas"]),
    ("Farmer’s Market Co-op", "Farmer’s Market Co-op", 42.00, ["Shops", "Groceries", "Organic", "Local"]),
    ("SEPTA", "SEPTA Transit", 5.00, ["Travel", "Public Transit"]),
    ("Costco", "Costco", 96.50, ["Shops", "Wholesale"]),
    ("H Mart", "H Mart", 34.90, ["Shops", "Groceries", "International"]),
    ("Uber Eats", "Uber Eats", 21.75, ["Food and Drink", "Delivery"]),
    ("MTA", "MTA Subway", 6.00, ["Travel", "Public Transit"]),
    ("Electric Utility", "Electric Utility", 62.40, ["Bills", "Utilities", "Electric"]),
]

def ensure_user(email: str, full_name: str) -> int:
    # Try to create; if exists, fetch list and find id
    r = requests.post(f"{BASE}/users/", json={
        "email": email,
        "password": "password123",
        "full_name": full_name,
    }, timeout=30)
    if r.status_code in (200, 201):
        return r.json().get("id", 1)
    # Fallback: list users and find by email
    users = requests.get(f"{BASE}/users/", timeout=30).json()
    for u in users:
        if u.get("email") == email:
            return u["id"]
    raise RuntimeError(f"User not found/created for {email}")


def generate_payload(user_id: int, months: int = 4):
    today = date.today()
    total_days = int(months * 30)
    start = today - timedelta(days=total_days)
    weeks = total_days // 7

    txs = []
    for w in range(weeks):
        week_start = start + timedelta(days=w*7)
        for i, (merchant_name, display_name, amount, cats) in enumerate(CATALOG):
            tx_date = week_start + timedelta(days=(i % 7))
            if tx_date > today:
                continue
            txs.append({
                "date": tx_date.isoformat(),
                "name": display_name,
                "merchant_name": merchant_name,
                "amount": float(amount),
                "iso_currency_code": "USD",
                "category": cats,
                "location": {"country": "USA"},
                "account_id": "named-seed",
            })
    return {"user_id": user_id, "transactions": txs}


def seed_named():
    summary = {}
    ids = {}
    for email, full_name in USERS:
        uid = ensure_user(email, full_name)
        ids[full_name] = uid
    for full_name, uid in ids.items():
        payload = generate_payload(uid, months=4)
        r = requests.post(f"{BASE}/transactions/ingest", json=payload, timeout=120)
        r.raise_for_status()
        summary[full_name] = r.json()
    return summary


if __name__ == "__main__":
    out = seed_named()
    print(out)
