from __future__ import annotations

import json
from typing import List, TypedDict, Optional

import requests

from ...core.config import get_settings


class ParsedItem(TypedDict, total=False):
    name: str
    price: Optional[float]
    qty: Optional[int]


SYSTEM_PROMPT = (
    "You extract structured receipt line items from plain text OCR. "
    "Return ONLY a JSON object with an 'items' array. Each item has 'name' (string), 'price' (number, in USD), and optional 'qty' (integer). "
    "Ignore headers, phone, order numbers, totals, tax, discounts, and promotions. "
    "If a product name appears on one line and its price on the next line, associate them. "
    "Use decimal prices (e.g., 1.29). Do not invent items."
)

USER_PROMPT_TEMPLATE = (
    "Extract items and prices from the receipt text. Rules:\n"
    "- Only use prices that APPEAR IN THE TEXT; do not invent or upscale values.\n"
    "- Prefer decimal amounts (e.g., 1.29). If a name line is followed by a price-only line, pair them.\n"
    "- If there is a TOTAL line with an amount, ensure the sum of item prices MATCHES that total by choosing the correct decimal prices from the text.\n"
    "- Ignore headers, totals/tax/subtotal lines as items.\n"
    "- Return strict JSON: {{\"items\":[{{\"name\":string,\"price\":number,\"qty\"?:number}}]}}.\n\n"
    "Receipt Text:\n"
    """{text}"""
)


def parse_items_with_cerebras(text: str) -> List[ParsedItem]:
    """Use Cerebras Inference API to parse receipt text into items.

    Returns a list of ParsedItem. Falls back to empty list on error.
    """
    settings = get_settings()
    api_key = settings.cerebras_api_key
    if not api_key or not text.strip():
        return []

    # Cerebras endpoint (OpenAI compatible v1/chat/completions)
    url = "https://api.cerebras.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama3.1-8b",  # lightweight, fast; adjust if you prefer bigger models
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text[:4000])},
        ],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(content or "{}")
        items = parsed.get("items") or []
        results: List[ParsedItem] = []
        for it in items:
            name = (it.get("name") or "").strip()
            price = it.get("price")
            qty = it.get("qty") if isinstance(it.get("qty"), int) else None
            if name and isinstance(price, (int, float)) and 0 < float(price) <= 10000:
                results.append({"name": name, "price": float(price), "qty": qty})
        return results
    except Exception:
        return []
