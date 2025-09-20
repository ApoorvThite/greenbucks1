from __future__ import annotations

from typing import Iterable, Optional

# Category keyword -> kgCO2e per USD (sector-level defaults)
CATEGORY_KG_CO2E_PER_USD: dict[str, float] = {
    # Very low
    "public transit": 0.04,
    "rail": 0.05,
    "bicycle": 0.02,
    # Low-mid
    "electric charging": 0.08,
    "groceries": 0.28,
    "coffee shop": 0.28,
    "restaurant": 0.35,
    "delivery": 0.45,
    # Mid
    "utilities": 0.35,
    "electric": 0.35,
    # High
    "ride share": 1.20,
    "gas": 1.50,
    "air": 2.50,
    "fast food": 0.40,
}

# Name keyword -> kgCO2e per USD (item-level hints)
NAME_KG_CO2E_PER_USD = [
    ("organic", 0.05),
    ("kale", 0.06),
    ("banana", 0.08),
    ("coffee", 0.25),
    ("beef", 5.0),
    ("chicken", 1.8),
    ("pork", 3.0),
    ("rice", 0.4),
    ("bread", 0.3),
    ("salad", 0.2),
    ("grocery", 0.30),
    ("starbucks", 0.28),
    ("shell", 1.50),
    ("uber", 1.20),
    ("lyft", 1.20),
    ("amtrak", 0.05),
]

DEFAULT_KG_CO2E_PER_USD = 0.50


def lookup_kg_co2e_per_usd(name: str, categories: Optional[Iterable[str]] = None) -> float:
    """Return a best-effort kgCO2e per USD based on categories or name keywords.

    Categories, if present, take precedence to ensure sector separation (e.g., transit vs ride share).
    """
    cats = {c.lower() for c in (categories or [])}
    for cat_key, val in CATEGORY_KG_CO2E_PER_USD.items():
        # Match exact token in categories set
        if cat_key in cats:
            return val

    # Fall back to name-based hints
    n = (name or "").lower()
    for key, val in NAME_KG_CO2E_PER_USD:
        if key in n:
            return val

    return DEFAULT_KG_CO2E_PER_USD
