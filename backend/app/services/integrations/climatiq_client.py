from __future__ import annotations

from typing import Optional, Tuple, Iterable
from decimal import Decimal
import requests

from ...core.config import get_settings
from .item_category_map import lookup_kg_co2e_per_usd


def _mock_estimate(name: str, price: float | None, qty: int | None, categories: Optional[Iterable[str]] = None) -> float:
    """Category-aware deterministic estimate: factor(kgCO2e/$) * price."""
    factor = lookup_kg_co2e_per_usd(name or "", categories)
    if price is None:
        price = 1.0
    return float(Decimal(str(factor)) * Decimal(str(price)))


def _best_effort_search_money_factor(session: requests.Session, api_key: str, query: str) -> Optional[dict]:
    """Try to find an emission factor that supports spend/money for the given query.
    Returns the factor dict or None.
    """
    try:
        url = "https://api.climatiq.io/emission-factors"
        resp = session.get(url, params={"query": query, "results_per_page": 10}, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        items = data.get("results") or data.get("items") or []
        # Heuristic: prefer factors that mention money/finance/spend and USD
        for it in items:
            unit = (it.get("unit") or "").lower()
            unit_type = (it.get("unit_type") or "").lower()
            # Many factors represent per currency unit, e.g., "USD"
            if "usd" in unit or "usd" in unit_type or "money" in unit_type or "spend" in unit_type:
                return it
        return items[0] if items else None
    except Exception:
        return None


def _estimate_using_factor(session: requests.Session, api_key: str, factor: dict, price: float) -> Optional[Tuple[float, str]]:
    """Try Climatiq /estimate. If not supported, return None to fallback. Returns (co2e, factor_id)."""
    try:
        url = "https://api.climatiq.io/estimate"
        # Many factors accept a payload with emission_factor.id and parameters for money
        # The request schema can vary; we attempt a generic money estimation.
        body = {
            "emission_factor": {"id": factor.get("id") or factor.get("uuid")},
            # Use documented schema: parameters.money = { amount, currency }
            "parameters": {
                "money": {
                    "amount": float(price),
                    "currency": "USD",
                }
            },
        }
        resp = session.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        # Try common response fields
        co2e = data.get("co2e") or data.get("co2e_total")
        if co2e is None:
            # Some responses return results list
            results = data.get("results") or []
            if results:
                co2e = results[0].get("co2e") or results[0].get("co2e_total")
        if co2e is None:
            return None
        factor_id = str(factor.get("id") or factor.get("uuid") or "")
        return (float(co2e), factor_id)
    except Exception:
        return None


async def estimate_item_footprint(
    name: str,
    price: float | None,
    qty: int | None,
    category: Optional[Iterable[str]] = None,
) -> Tuple[float, str, Optional[str]]:
    """Return (kgCO2e, source, factor_id) for a single item.

    source: 'live' if Climatiq API used, else 'fallback'. factor_id may be None when fallback.
    """
    settings = get_settings()
    if not settings.use_real_climatiq or not settings.climatiq_api_key:
        return (_mock_estimate(name, price, qty, category), "fallback", None)

    try:
        if price is None or price <= 0:
            # Without spend, fallback
            return (_mock_estimate(name, price, qty, category), "fallback", None)
        session = requests.Session()
        # 1) Search a relevant factor for the item name with sector hints
        def sector_hints(nm: str, cats: Optional[Iterable[str]]) -> list[str]:
            nm_l = (nm or "").lower()
            cats_l = {c.lower() for c in (cats or [])}
            hints: list[str] = []
            # Ride share / taxi
            if any(k in nm_l for k in ["uber", "lyft", "ride"]) or any("ride share" in c for c in cats_l):
                hints += ["taxi services", "ride hailing services", "transportation services"]
            # Public transit / rail / subway
            if any(k in nm_l for k in ["mta", "subway", "metro", "amtrak"]) or any(k in cats_l for k in ["public transit", "rail"]):
                hints += ["public transit services", "rail passenger transport"]
            # Gasoline / fuel
            if "shell" in nm_l or any(k in cats_l for k in ["gas", "fuel"]):
                hints += ["gasoline retail", "petroleum fuel retail"]
            # Utilities electricity
            if any(k in nm_l for k in ["utility", "utilities"]) or any(k in cats_l for k in ["electric", "utilities"]):
                hints += ["electric utilities spend", "electricity services"]
            # Groceries / retail food
            if any(k in cats_l for k in ["groceries"]) or any(k in nm_l for k in ["grocery", "market", "mart", "costco", "h mart", "whole foods", "trader joe"]):
                hints += ["grocery retail", "food retail"]
            # Coffee shops / restaurants
            if any(k in cats_l for k in ["coffee shop", "restaurant", "fast food"]) or any(k in nm_l for k in ["starbucks", "chipotle", "mcdonald", "blue bottle"]):
                hints += ["food services", "coffee shop services"]
            # Transport rail generic
            if "amtrak" in nm_l:
                hints += ["rail passenger transport"]
            return hints

        hints = sector_hints(name, category)
        factor = None
        # Try: name + first hint that yields a factor; else name alone
        for h in hints:
            factor = _best_effort_search_money_factor(session, settings.climatiq_api_key, f"{name} {h}")
            if factor:
                break
        if not factor:
            factor = _best_effort_search_money_factor(session, settings.climatiq_api_key, name)
        # 2) If found, try estimate
        if factor:
            res = _estimate_using_factor(session, settings.climatiq_api_key, factor, float(price))
            if res is not None:
                co2e, fid = res
                return (co2e, "live", fid)
        # 3) Fallback path: if we had sector hints but couldn't find a specific factor,
        #    prefer deterministic category mapping to avoid uniform scores.
        if hints:
            return (_mock_estimate(name, price, qty, category), "fallback", None)
        # Otherwise, attempt a generic economy-wide spend factor
        generic_factor = _best_effort_search_money_factor(session, settings.climatiq_api_key, "spend economy")
        if generic_factor:
            res = _estimate_using_factor(session, settings.climatiq_api_key, generic_factor, float(price))
            if res is not None:
                co2e, fid = res
                return (co2e, "live", fid)
        # 4) Final fallback: deterministic mapping
        return (_mock_estimate(name, price, qty, category), "fallback", None)
    except Exception:
        return (_mock_estimate(name, price, qty, category), "fallback", None)
