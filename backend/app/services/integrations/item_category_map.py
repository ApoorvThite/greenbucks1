from __future__ import annotations

# Simple keyword -> kgCO2e per USD fallback factors
# These are illustrative and not authoritative; adjust as needed.
FALLBACK_KG_CO2E_PER_USD = [
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
    ("grocery", 0.3),
    ("shirt", 1.2),
    ("electronics", 0.6),
    ("toy", 0.5),
    ("book", 0.2),
]

DEFAULT_KG_CO2E_PER_USD = 0.5


def lookup_kg_co2e_per_usd(name: str) -> float:
    n = (name or "").lower()
    for key, val in FALLBACK_KG_CO2E_PER_USD:
        if key in n:
            return val
    return DEFAULT_KG_CO2E_PER_USD
