from __future__ import annotations

import base64
import json
from typing import List, Optional, TypedDict

import requests
from io import BytesIO

try:
    from PIL import Image, ImageOps, ImageFilter
    import pytesseract
    HAS_LOCAL_OCR = True
except Exception:
    HAS_LOCAL_OCR = False

# Optional OpenCV for stronger preprocessing
try:
    import cv2
    import numpy as np
    HAS_CV = True
except Exception:
    HAS_CV = False

from ...core.config import get_settings
from .cerebras_client import parse_items_with_cerebras


class ParsedItem(TypedDict, total=False):
    name: str
    price: Optional[float]
    qty: Optional[int]


def _mock_parse(image_bytes: bytes) -> List[ParsedItem]:
    # Very simple mock: return a single unknown item; callers will fallback on spend factors
    return [{"name": "Unknown Item", "price": None, "qty": None}]


def _looks_like_pdf(blob: bytes) -> bool:
    return blob[:5] == b"%PDF-"


async def extract_text(image_bytes: bytes) -> tuple[str, dict]:
    """Call Google Vision to extract full OCR text.

    Returns a tuple: (text, diagnostics)
    diagnostics includes last_url, status_code, and response_excerpt when available for debugging.
    In mock/disabled mode, returns ("", {}).
    """
    settings = get_settings()
    if not settings.use_real_ocr or not settings.google_vision_api_key:
        # Don't call Vision; let caller optionally run local OCR
        return "", {"note": "Vision disabled; consider local OCR"}

    diagnostics: dict = {}
    session = requests.Session()
    try:
        if _looks_like_pdf(image_bytes):
            # Use files:annotate for PDFs (sync for first few pages)
            url = f"https://vision.googleapis.com/v1/files:annotate?key={settings.google_vision_api_key}"
            payload = {
                "requests": [
                    {
                        "inputConfig": {
                            "mimeType": "application/pdf",
                            "content": base64.b64encode(image_bytes).decode("utf-8"),
                        },
                        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                        # Process first 5 pages by default
                        "pages": [1, 2, 3, 4, 5],
                    }
                ]
            }
            resp = session.post(url, json=payload, timeout=30)
            diagnostics.update({
                "last_url": url.split("?")[0],
                "status_code": resp.status_code,
            })
            # Don't raise; we want to capture diagnostics
            data = resp.json() if resp.ok else None
            # files:annotate returns responses[].responses[].fullTextAnnotation
            text = ""
            try:
                file_resp = (data.get("responses") or [{}])[0]
                # Some versions embed responses under responses[0].responses
                inner = (file_resp.get("responses") or [])
                if inner:
                    texts = [
                        (pg.get("fullTextAnnotation", {}) or {}).get("text", "")
                        for pg in inner
                    ]
                    text = "\n".join([t for t in texts if t])
                else:
                    text = (file_resp.get("fullTextAnnotation", {}) or {}).get("text", "")
            except Exception:
                text = ""
            if resp.ok:
                diagnostics["response_excerpt"] = (json.dumps(data)[:500] if data else "")
            else:
                diagnostics["response_excerpt"] = (resp.text or "")[:500]
            if text:
                return text, diagnostics
            # Fall through to try image path as a fallback

        # Image path with DOCUMENT_TEXT_DETECTION
        url_img = f"https://vision.googleapis.com/v1/images:annotate?key={settings.google_vision_api_key}"
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload_img = {
            "requests": [
                {
                    "image": {"content": img_b64},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }
            ]
        }
        resp_img = session.post(url_img, json=payload_img, timeout=20)
        diagnostics.update({
            "last_url": url_img.split("?")[0],
            "status_code": resp_img.status_code,
        })
        data_img = resp_img.json() if resp_img.ok else None
        text = (
            (data_img.get("responses", [{}])[0]).get("fullTextAnnotation", {})
        ).get("text", "")
        if not text:
            # Fallback to TEXT_DETECTION if document text empty
            payload_txt = {
                "requests": [
                    {
                        "image": {"content": img_b64},
                        "features": [{"type": "TEXT_DETECTION"}],
                    }
                ]
            }
            resp_txt = session.post(url_img, json=payload_txt, timeout=20)
            diagnostics.update({
                "last_url": url_img.split("?")[0] + "#TEXT_DETECTION",
                "status_code": resp_txt.status_code,
            })
            data_txt = resp_txt.json() if resp_txt.ok else None
            anns = (data_txt.get("responses", [{}])[0]).get("textAnnotations", [])
            if anns:
                text = anns[0].get("description", "") or ""
            if resp_txt.ok:
                diagnostics["response_excerpt"] = (json.dumps(data_txt)[:500] if data_txt else "")
            else:
                diagnostics["response_excerpt"] = (resp_txt.text or "")[:500]
        else:
            diagnostics["response_excerpt"] = (json.dumps(data_img)[:500] if data_img else "")
        return text or "", diagnostics
    except Exception as e:
        diagnostics.setdefault("error", str(e))
        return "", diagnostics


def parse_items_from_text(text: str) -> List[ParsedItem]:
    """Parse multiple line items from raw OCR text using several regex strategies.

    Supports:
    - Inline name + price
    - Column-like spacing
    - Name line followed by price-only next line
    Skips subtotal/tax/total/payment and noisy lines.
    """
    if not text:
        return []
    import re

    STOPWORDS = {
        "subtotal", "sub total", "tax", "total", "grand total", "balance", "change",
        "payment", "visa", "mastercard", "amex", "debit", "credit", "cash",
    }
    EXCLUDE_KEYWORDS = {
        "order", "phone", "date", "time", "invoice", "register", "receipt",
        "discount", "% off", "%", "cashier", "store", "address",
    }
    UNIT_KEYWORDS = {"lb", "lbs", "pk", "ct", "ea", "oz", "kg", "g"}
    PRICE = r"(?P<price>(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)"
    patterns = [
        re.compile(rf"^(?P<name>.+?)\s+\$?{PRICE}$", re.IGNORECASE),
        re.compile(rf"^(?P<qty>\d+)\s*[xX*]\s*(?P<name>.+?)\s+\$?{PRICE}$", re.IGNORECASE),
        re.compile(rf"^(?P<name>.+?)\s+@\s*\$?{PRICE}$", re.IGNORECASE),
        re.compile(rf"^(?P<name>.+?)\s{{2,}}\$?{PRICE}$", re.IGNORECASE),
        re.compile(rf"^\$?{PRICE}\s+(?P<name>.+)$", re.IGNORECASE),
    ]

    items: List[ParsedItem] = []
    lines = text.splitlines()
    PRICE_ONLY = re.compile(rf"^\$?{PRICE}$", re.IGNORECASE)

    def is_noisy(s: str) -> bool:
        if not s:
            return True
        letters = sum(ch.isalpha() for ch in s)
        digits = sum(ch.isdigit() for ch in s)
        alnum = letters + digits
        non_alnum = sum(not ch.isalnum() and not ch.isspace() for ch in s)
        if alnum == 0:
            return True
        return (non_alnum / max(1, len(s))) > 0.4 and letters < 2

    pending_name: Optional[str] = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or len(line) < 2:
            continue
        l = line.lower()
        if any(sw in l for sw in STOPWORDS):
            continue
        if is_noisy(line):
            continue
        # Remove dotted leaders
        line = re.sub(r"\.{2,}\s*", " ", line)
        matched = False
        for pat in patterns:
            m = pat.search(line)
            if m:
                name = (m.groupdict().get("name") or "").strip("-: .\t")
                price_s = m.groupdict().get("price")
                qty_s = m.groupdict().get("qty")
                price = None
                try:
                    if price_s:
                        price = float(price_s.replace(",", ""))
                except Exception:
                    price = None
                qty = None
                if qty_s:
                    try:
                        qty = int(qty_s)
                    except Exception:
                        qty = None
                name_l = name.lower()
                if price is not None and (price <= 0 or price > 10000):
                    continue
                if any(k in name_l for k in EXCLUDE_KEYWORDS):
                    continue
                if not any(ch.isalpha() for ch in name):
                    continue
                if len(name) < 2:
                    continue
                items.append({"name": name, "price": price, "qty": qty})
                matched = True
                break
        if not matched:
            m2 = re.search(rf"\$?{PRICE}(?!.*\d)", line)
            if m2:
                try:
                    price = float(m2.group("price").replace(",", ""))
                except Exception:
                    price = None
                before = line[: m2.start()].strip("-: .\t")
                after = line[m2.end():].strip("-: .\t")
                name = before or after
                name_l = name.lower()
                if (
                    price is not None
                    and 0 < price <= 10000
                    and name
                    and not any(sw in name_l for sw in STOPWORDS)
                    and not any(k in name_l for k in EXCLUDE_KEYWORDS)
                    and any(ch.isalpha() for ch in name)
                    and len(name) >= 2
                ):
                    items.append({"name": name, "price": price, "qty": None})
                matched = True
        if not matched:
            # Name line followed by price-only next line
            if PRICE_ONLY.match(line):
                try:
                    p = float(PRICE_ONLY.match(line).group("price").replace(",", ""))
                except Exception:
                    p = None
                if pending_name and p is not None and 0 < p <= 10000:
                    if not any(k in pending_name.lower() for k in EXCLUDE_KEYWORDS):
                        items.append({"name": pending_name, "price": p, "qty": None})
                    pending_name = None
                continue
            if any(ch.isalpha() for ch in line) and not any(k in l for k in EXCLUDE_KEYWORDS):
                pending_name = line

    # Deduplicate by (name, price)
    dedup = {}
    for it in items:
        key = (it.get("name", "").lower(), round((it.get("price") or 0.0), 2))
        dedup[key] = it
    items = list(dedup.values())

    # Total-based decimal inference scaling (if needed)
    try:
        totals = []
        for raw_line in text.splitlines():
            s = raw_line.strip().lower()
            if "total" in s and not any(x in s for x in ["subtotal", "sub total", "tax"]):
                m = re.search(r"\$?((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)", s)
                if m:
                    try:
                        totals.append(float(m.group(1).replace(",", "")))
                    except Exception:
                        pass
        if totals:
            target_total = sorted(totals)[-1]
            prices = [it.get("price") for it in items if isinstance(it.get("price"), (int, float))]
            if prices:
                sum_prices = sum(prices)
                if target_total > 0 and 0.95 <= (sum_prices / (target_total * 100)) <= 1.05:
                    for it in items:
                        if isinstance(it.get("price"), (int, float)):
                            it["price"] = round(float(it["price"]) / 100.0, 2)
    except Exception:
        pass

    return items


def _preprocess_image_bytes_cv(image_bytes: bytes) -> Optional[Image.Image]:
    """Use OpenCV to enhance image for OCR: grayscale, denoise, adaptive threshold, morphology."""
    if not HAS_CV:
        return None
    try:
        data = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        # Resize up if small
        h, w = img.shape[:2]
        if min(h, w) < 900:
            scale = max(1.5, 900.0 / float(min(h, w)))
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        # Denoise and enhance edges
        img = cv2.bilateralFilter(img, 9, 75, 75)
        # Adaptive threshold to reveal faint decimals
        th = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 35, 10)
        # Morph close to connect broken digits
        kernel = np.ones((2, 2), np.uint8)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=1)
        # Convert back to PIL
        pil = Image.fromarray(th)
        return pil
    except Exception:
        return None


def _local_ocr_image_bytes(image_bytes: bytes) -> str:
    """Run local OCR via pytesseract on image bytes. Returns raw text or empty string."""
    if not HAS_LOCAL_OCR:
        return ""
    try:
        # Prefer OpenCV preprocessing if available
        img = _preprocess_image_bytes_cv(image_bytes)
        if img is None:
            img = Image.open(BytesIO(image_bytes))
            img = ImageOps.grayscale(img)
            # Resize up for better OCR if small
            try:
                w, h = img.size
                if min(w, h) < 900:
                    scale = max(1.5, 900 / float(min(w, h)))
                    img = img.resize((int(w * scale), int(h * scale)))
            except Exception:
                pass
            img = ImageOps.autocontrast(img)
            img = img.filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(img)
        return text or ""
    except Exception:
        return ""


def get_local_ocr_text(image_bytes: bytes) -> str:
    """Public helper to get local OCR text if available; returns empty string otherwise."""
    return _local_ocr_image_bytes(image_bytes)


def _local_text_from_data(image_bytes: bytes) -> str:
    """Assemble plain text from pytesseract.image_to_data by grouping tokens into lines.

    This often recovers decimals that image_to_string misses by preserving token positions.
    """
    if not HAS_LOCAL_OCR:
        return ""
    try:
        # Prefer preprocessed image
        img = _preprocess_image_bytes_cv(image_bytes)
        if img is None:
            img = Image.open(BytesIO(image_bytes))
            img = ImageOps.grayscale(img)
            img = ImageOps.autocontrast(img)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config='--oem 3 --psm 6')
        n = len(data.get("text", []))
        words = []
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            try:
                left = int(data.get("left", [0])[i])
                top = int(data.get("top", [0])[i])
            except Exception:
                left, top = 0, 0
            words.append({"text": txt, "left": left, "top": top})
        if not words:
            return ""
        # Group by horizontal bands (similar 'top')
        words.sort(key=lambda w: w["top"])
        lines = []
        tol = 12
        for w in words:
            if not lines or abs(w["top"] - lines[-1][0]["top"]) > tol:
                lines.append([w])
            else:
                lines[-1].append(w)
        # Sort within lines by left and join
        out_lines = []
        for line in lines:
            line.sort(key=lambda w: w["left"])
            out_lines.append(" ".join(tok["text"] for tok in line))
        return "\n".join(out_lines)
    except Exception:
        return ""


async def parse_receipt_diagnostics(image_bytes: bytes) -> tuple[List[ParsedItem], dict]:
    """Parse receipt items and return diagnostics including parser_used and text_source."""
    diag: dict = {"parser_used": None, "text_source": None}
    settings = get_settings()
    # First try Google Vision if enabled
    text = ""
    if settings.use_real_ocr and settings.google_vision_api_key:
        text, _diag = await extract_text(image_bytes)
        diag["text_source"] = "google_vision" if text else None
    # If Vision yielded nothing and it's an image, try local OCR
    if not text and not _looks_like_pdf(image_bytes):
        local_text = _local_ocr_image_bytes(image_bytes)
        data_text = _local_text_from_data(image_bytes)
        # Heuristic: prefer the text with stronger price signal (more decimal prices)
        def price_signal(s: str) -> int:
            import re
            if not s:
                return 0
            return len(re.findall(r"\b\$?\d+\.\d{2}\b", s))
        ps_local = price_signal(local_text)
        ps_data = price_signal(data_text)
        chosen = None
        if ps_data > ps_local:
            chosen = (data_text or "").strip()
            src = "local_data"
        else:
            chosen = (local_text or "").strip()
            src = "local_ocr" if chosen else None
        if chosen:
            text = chosen
            diag["text_source"] = src

    items: List[ParsedItem] = []
    # Try Cerebras first
    if text and settings.use_cerebras_parser:
        try:
            items = parse_items_with_cerebras(text)
            if items:
                diag["parser_used"] = "cerebras"
        except Exception as e:
            diag["cerebras_error"] = str(e)
            items = []
    # Fallback to regex/text parsing
    if not items:
        items = parse_items_from_text(text)
        if items:
            diag["parser_used"] = "regex"
    # If we have few items from text and it's an image, try data-based extraction to capture right-aligned prices
    if (not _looks_like_pdf(image_bytes)) and len(items) < 5 and HAS_LOCAL_OCR:
        try:
            extra = _local_items_by_tesseract_data(image_bytes)
            # Merge dedup by (name, price)
            seen = {(it.get("name", "").lower(), round((it.get("price") or 0.0), 2)) for it in items}
            added = 0
            for it in extra:
                key = (it.get("name", "").lower(), round((it.get("price") or 0.0), 2))
                if key not in seen:
                    items.append(it)
                    seen.add(key)
                    added += 1
            if added:
                diag.setdefault("augmenters", []).append("tesseract_data")
                if not diag.get("parser_used"):
                    diag["parser_used"] = "tesseract_data"
        except Exception as e:
            diag["tesseract_data_error"] = str(e)
    if not items:
        diag["fallback"] = "mock"
    return (items or _mock_parse(image_bytes), diag)


async def parse_receipt(image_bytes: bytes) -> List[ParsedItem]:
    items, _ = await parse_receipt_diagnostics(image_bytes)
    return items


def _local_items_by_tesseract_data(image_bytes: bytes) -> List[ParsedItem]:
    """Associate nearest right-side numeric token with left-side item tokens using image_to_data coordinates.

    - Group words into horizontal bands by 'top' within a tolerance.
    - For each band, split into left (item) tokens and right (price) tokens by median 'left'.
    - Reconstruct price from adjacent tokens (handle '$', digits, '.', commas).
    - Prefer tokens with decimals or '$'; avoid integers that look like weights/packs (lb, pk, ct, etc.).
    """
    if not HAS_LOCAL_OCR:
        return []
    def _run_psm(psm: int):
        img = _preprocess_image_bytes_cv(image_bytes)
        if img is None:
            img = Image.open(BytesIO(image_bytes))
            img = ImageOps.grayscale(img)
            img = ImageOps.autocontrast(img)
        return pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=f'--oem 3 --psm {psm}')

    try:
        data = _run_psm(6)
    except Exception:
        return []

    import re
    UNIT_TOKS = {"lb", "lbs", "pk", "ct", "ea", "oz", "kg", "g"}
    PRICE_FULL = re.compile(r"^(?:\$)?(?P<p>(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)$")

    n = len(data.get("text", []))
    words = []
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        left = int(data.get("left", [0])[i])
        top = int(data.get("top", [0])[i])
        conf = int(float(data.get("conf", ["-1"][i]))) if i < len(data.get("conf", [])) else -1
        if conf < 0:
            continue
        words.append({"text": txt, "left": left, "top": top})

    # Group into horizontal bands with tolerance
    words.sort(key=lambda w: w["top"])
    bands: List[List[dict]] = []
    tol = 12
    for w in words:
        if not bands:
            bands.append([w])
            continue
        if abs(w["top"] - bands[-1][0]["top"]) <= tol:
            bands[-1].append(w)
        else:
            bands.append([w])

    # Build a global index of numeric tokens to support nearest-neighbor association
    import math
    numeric_tokens = []
    for w in words:
        t = w["text"].replace(" ", "")
        m = PRICE_FULL.match(t)
        if m:
            try:
                numeric_tokens.append({"left": w["left"], "top": w["top"], "price": float(m.group("p").replace(",", ""))})
                continue
            except Exception:
                pass
        if t.isdigit() and 2 <= len(t) <= 6:
            # avoid unit contexts later
            try:
                v = int(t)
                if 10 <= v <= 50000:
                    numeric_tokens.append({"left": w["left"], "top": w["top"], "price_int": v})
            except Exception:
                pass

    results: List[ParsedItem] = []
    for idx_band, band in enumerate(bands):
        band.sort(key=lambda w: w["left"])  # left to right
        if len(band) < 2:
            continue
        # Split around median 'left' to approximate left column vs right column
        xs = [w["left"] for w in band]
        median_x = sorted(xs)[len(xs)//2]
        left_side = [w for w in band if w["left"] <= median_x]
        right_side = [w for w in band if w["left"] > median_x]
        if not left_side or not right_side:
            continue

        # Build candidate name from left_side tokens
        name = " ".join(w["text"] for w in left_side).strip("-: .\t")
        name_l = name.lower()
        if not name or not any(ch.isalpha() for ch in name):
            continue
        if any(sw in name_l for sw in {"subtotal", "sub total", "tax", "total", "grand total"}):
            continue
        if any(k in name_l for k in {"order", "phone", "date", "time", "invoice", "register", "receipt", "discount", "% off", "%", "cashier", "store", "address"}):
            continue

        # Reconstruct rightmost numeric from right_side (contiguous tokens)
        best_price = None
        # Consider contiguous suffix tokens
        for k in range(len(right_side)-1, -1, -1):
            # Try joining up to 3 tokens (to capture cases like '$', '1.29')
            for span in range(1, 4):
                if k-span+1 < 0:
                    continue
                seg = "".join(t["text"] for t in right_side[k-span+1:k+1]).replace(" ", "")
                m = PRICE_FULL.match(seg)
                if m:
                    try:
                        best_price = float(m.group("p").replace(",", ""))
                        break
                    except Exception:
                        pass
            if best_price is not None:
                break
        # Do NOT use integer-only tokens as prices here; avoid misreading weights/packs as prices

        # Global nearest-neighbor: if still none, find the closest numeric token to the right in the same y-band region
        if best_price is None and numeric_tokens:
            # Compute band vertical range
            top_vals = [w["top"] for w in band]
            band_top = min(top_vals)
            band_bottom = max(top_vals)
            name_right = max(w["left"] for w in left_side)
            candidate = None
            best_dist = 1e9
            for nt in numeric_tokens:
                px = nt.get("left", 0)
                py = nt.get("top", 0)
                if px <= name_right:
                    continue
                # within vertical proximity to band
                if py < band_top - tol or py > band_bottom + tol:
                    continue
                # distance metric prefers minimal horizontal distance, then vertical
                dx = px - name_right
                dy = 0 if band_top <= py <= band_bottom else min(abs(py - band_top), abs(py - band_bottom))
                dist = dx + 0.25 * dy
                if dist < best_dist:
                    candidate = nt
                    best_dist = dist
            if candidate is not None and "price" in candidate:
                best_price = candidate["price"]

        # Cross-band search: if still none and the name line contains unit tokens (e.g., '1 lb'),
        # look in the next one or two bands to the right for the nearest decimal/$ price token
        if best_price is None:
            neighbor_text = " ".join(w["text"].lower() for w in band)
            if any(u in neighbor_text for u in UNIT_TOKS):
                for j in (idx_band + 1, idx_band + 2):
                    if j >= len(bands):
                        break
                    nb = bands[j]
                    nb.sort(key=lambda w: w["left"])  # ensure left-to-right
                    # Consider only tokens that are to the right of the name
                    right_tokens = [w for w in nb if w["left"] > name_right]
                    # Try to reconstruct a price from up to 3-token suffixes
                    for k in range(len(right_tokens)-1, -1, -1):
                        for span in range(1, 4):
                            if k-span+1 < 0:
                                continue
                            seg = "".join(t["text"] for t in right_tokens[k-span+1:k+1]).replace(" ", "")
                            m = PRICE_FULL.match(seg)
                            if m:
                                try:
                                    best_price = float(m.group("p").replace(",", ""))
                                    break
                                except Exception:
                                    pass
                        if best_price is not None:
                            break
                    if best_price is not None:
                        break

        if best_price is None or not (0 < best_price <= 10000):
            continue
        results.append({"name": name, "price": best_price, "qty": None})

    # If results are still too few, try an alternate PSM and merge
    if len(results) < 3:
        try:
            alt = _run_psm(4)
            # Merge minimal: rebuild words and bands quickly could be heavy; skip for now if alt empty
        except Exception:
            pass

    # Dedup
    ded = {}
    for it in results:
        key = (it["name"].lower(), round(it["price"], 2))
        ded[key] = it
    return list(ded.values())
