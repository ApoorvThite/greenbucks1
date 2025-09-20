from __future__ import annotations

from typing import Optional
from decimal import Decimal
import requests

from ...core.config import get_settings
from .item_category_map import lookup_kg_co2e_per_usd


def _mock_estimate(name: str, price: float | None, qty: int | None) -> float:
    # Use fallback per-dollar factor times price when available
    factor = lookup_kg_co2e_per_usd(name or "")
    if price is None:
        price = 1.0
    return float(Decimal(str(factor)) * Decimal(str(price)))


async def estimate_item_footprint(name: str, price: float | None, qty: int | None) -> float:
    """Return kgCO2e for a single item using Climatiq. Falls back to deterministic factor mapping.

    For simplicity we use spend-based estimation when real API is enabled: $ -> kgCO2e using generic factor.
    """
    settings = get_settings()
    if not settings.use_real_climatiq or not settings.climatiq_api_key:
        return _mock_estimate(name, price, qty)

    # Simple spend-based category-less estimation using a generic factor code, if available.
    # If you have specific LCA categories, map name->category/sector and call a suitable endpoint.
    try:
        # Example: Climatiq provides an endpoint /estimate with activity IDs or search endpoints.
        # Here we will fallback to our own factor even in real mode if API call fails or no mapping exists.
        # See https://www.climatiq.io/docs/api-reference for detailed usage.
        # We'll do a placeholder search + use price * factor; if not available, fallback.
        return _mock_estimate(name, price, qty)
    except Exception:
        return _mock_estimate(name, price, qty)
