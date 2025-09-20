from __future__ import annotations

import base64
import json
from typing import List, Optional, TypedDict

import requests

from ...core.config import get_settings


class ParsedItem(TypedDict, total=False):
    name: str
    price: Optional[float]
    qty: Optional[int]


def _mock_parse(image_bytes: bytes) -> List[ParsedItem]:
    # Very simple mock: return a single unknown item; callers will fallback on spend factors
    return [{"name": "Unknown Item", "price": None, "qty": None}]


async def parse_receipt(image_bytes: bytes) -> List[ParsedItem]:
    """Parse receipt items using Google Vision OCR (Text Detection). Returns list of items.

    In real mode, calls Google Vision API and does a naive line/price regex extraction.
    In mock mode (no key or disabled), returns a fallback single item.
    """
    settings = get_settings()
    if not settings.use_real_ocr or not settings.google_vision_api_key:
        return _mock_parse(image_bytes)

    # Build request for Google Vision v1 images:annotate
    url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.google_vision_api_key}"
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "requests": [
            {
                "image": {"content": img_b64},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # Extract full text
        text = (
            data.get("responses", [{}])[0]
            .get("fullTextAnnotation", {})
            .get("text", "")
        )
        if not text:
            return _mock_parse(image_bytes)
        # Naive parse: each line, try to split trailing price using regex
        import re

        items: List[ParsedItem] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or len(line) < 2:
                continue
            # match e.g. "Bananas 1.23" or "Coffee $4.50"
            m = re.search(r"(?P<name>.*?)[\s\t]+\$?(?P<price>\d+\.\d{1,2})$", line)
            if m:
                name = m.group("name").strip("-: .\t")
                try:
                    price = float(m.group("price"))
                except Exception:
                    price = None
                if name:
                    items.append({"name": name, "price": price, "qty": None})
        return items or _mock_parse(image_bytes)
    except Exception:
        # graceful fallback
        return _mock_parse(image_bytes)
