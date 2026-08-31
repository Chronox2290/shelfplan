"""Coles product lookup, without an API key.

Coles renders search results on the server and embeds them in the page's
__NEXT_DATA__ blob, so the products are readable from the search page itself.
The old /api/bff/products route needs a `subscription-key` that the site no
longer exposes to the browser -- it is server-side now -- which is why the
key-based path in coles.py cannot be made to work from a client any more.

Emits the same record shape as catalog.search so both stores are comparable.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import re
import threading
import time

import requests

STORE_NAME = "coles"
SEARCH_URL = "https://www.coles.com.au/search/products"

_NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_SIZE_TOKEN = re.compile(r"([\d.]+)\s*(kg|g|l|ml)\b", re.I)
_TO_GRAMS = {"kg": 1000.0, "g": 1.0, "l": 1000.0, "ml": 1.0}

# Coles serves a "Pardon Our Interruption" interstitial when requests arrive
# too quickly from one address, and the block outlasts the burst that caused
# it. One request at a time, spaced out, plus a cache so a repeated shopping
# list costs nothing.
_MIN_INTERVAL_S = 1.8
_CACHE_TTL_S = 30 * 60

_lock = threading.Lock()
_last_request_at = 0.0
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (time.monotonic() - hit[0]) < _CACHE_TTL_S:
            return hit[1]
        if hit:
            del _cache[key]
    return None


def _remember(key: str, value: Dict[str, Any]) -> None:
    # Never cache a challenge or an error -- it would poison the next 30 min.
    if value.get("status") != "success":
        return
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def parse_pack_grams(product: Dict[str, Any]) -> Optional[float]:
    """Pack size in grams from the `size` text ("550g", "1kg", "500g - 650g")."""
    text = product.get("size") or ""
    if not isinstance(text, str):
        return None
    grams = [
        float(n) * _TO_GRAMS[u.lower()]
        for n, u in _SIZE_TOKEN.findall(text)
        if u.lower() in _TO_GRAMS
    ]
    if not grams:
        return None
    return (min(grams) + max(grams)) / 2 if len(grams) > 1 else grams[0]


# "$11.00/ 1kg", "$4.02/ 100g", "$1.36/100 g"
_COMPARABLE = re.compile(
    r"\$\s*([\d.]+)\s*/\s*([\d.]*)\s*(kg|g|l|ml)\b", re.I)


def parse_unit_price_per_kg(pricing: Dict[str, Any]) -> Optional[float]:
    """Per-kilogram price, taken from the displayed comparable price.

    The structured `unit` block cannot be trusted on its own: some lines carry
    ofMeasureType "g" with ofMeasureQuantity 1 while the shopper-facing string
    reads "$14.50/ 1kg" -- believing the block gives $14,500/kg. The comparable
    string is what Coles shows and is internally consistent, so it wins; the
    block is only a fallback for rows that have no string.
    """
    text = pricing.get("comparable")
    if isinstance(text, str):
        match = _COMPARABLE.search(text)
        if match:
            price = _num(match.group(1))
            qty = _num(match.group(2)) or 1.0
            measure = match.group(3).lower()
            grams = qty * _TO_GRAMS[measure]
            if price is not None and grams:
                return price * 1000.0 / grams

    unit = pricing.get("unit") or {}
    price = _num(unit.get("price"))
    qty = _num(unit.get("ofMeasureQuantity"))
    measure = (unit.get("ofMeasureType") or unit.get("ofMeasureUnits") or "").lower()
    if price is None or qty is None or measure not in _TO_GRAMS:
        return None
    grams = qty * _TO_GRAMS[measure]
    return price * 1000.0 / grams if grams else None


COLES_IMAGE_HOST = "https://productimages.coles.com.au"


def pick_image(product: Dict[str, Any]) -> str:
    """Best available image URL for a Coles product.

    Their payload carries an `imageUris` list whose exact shape is not
    documented, so every plausible key is tried and anything unrecognised
    yields an empty string rather than a broken image.
    """
    uris = product.get("imageUris")
    if isinstance(uris, str):
        candidates = [uris]
    elif isinstance(uris, list):
        candidates = []
        for entry in uris:
            if isinstance(entry, str):
                candidates.append(entry)
            elif isinstance(entry, dict):
                for key in ("uri", "url", "href", "path"):
                    if isinstance(entry.get(key), str):
                        candidates.append(entry[key])
                        break
    else:
        candidates = []

    for uri in candidates:
        uri = uri.strip()
        if not uri:
            continue
        if uri.startswith("http"):
            return uri
        return COLES_IMAGE_HOST + ("" if uri.startswith("/") else "/") + uri
    return ""


def normalise(product: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one Coles result into the shared record shape."""
    pricing = product.get("pricing") or {}
    pack_g = parse_pack_grams(product)
    per_kg = parse_unit_price_per_kg(pricing)
    listed = _num(pricing.get("now")) or _num(pricing.get("rawPriceNow"))

    if per_kg is not None and pack_g is not None:
        pack_price = round(per_kg * pack_g / 1000.0, 2)
    else:
        pack_price = round(listed, 2) if listed is not None else None

    variable_weight = bool(
        listed is not None and pack_price is not None
        and abs(listed - pack_price) > max(0.05, 0.05 * pack_price)
    )

    was = _num(pricing.get("was"))
    name = product.get("name") or ""
    brand = product.get("brand") or ""
    # Coles splits brand out of the name; Woolworths does not. Join them so the
    # matcher sees comparable strings across the two stores.
    full_name = f"{brand} {name}".strip() if brand and not name.lower().startswith(
        brand.lower()) else name

    return {
        "name": full_name,
        "brand": brand,
        "stockcode": product.get("id"),
        # Coles does not publish a barcode in the search payload.
        "barcode": "",
        "pack_price": pack_price,
        "pack_g": round(pack_g) if pack_g is not None else None,
        "per_kg": round(per_kg, 2) if per_kg is not None else None,
        "cup_string": pricing.get("comparable") or "",
        "package_size": product.get("size") or "",
        "listed_price": round(listed, 2) if listed is not None else None,
        "variable_weight": variable_weight,
        "on_special": bool(pricing.get("promotionType")) or bool(
            pricing.get("onlineSpecial")),
        "was_price": round(was, 2) if was is not None else None,
        "offer": pricing.get("offerDescription") or "",
        "in_stock": bool(product.get("availability", True)),
        "available": bool(product.get("availability", True)),
        "image": pick_image(product),
        "url": (
            f"https://www.coles.com.au/product/{product.get('id')}"
            if product.get("id") else ""
        ),
        "store": STORE_NAME,
    }


def _extract_results(html: str) -> List[Dict[str, Any]]:
    match = _NEXT_DATA.search(html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []
    results = (
        data.get("props", {})
        .get("pageProps", {})
        .get("searchResults", {})
        .get("results")
    )
    return results if isinstance(results, list) else []


def search(query: str, limit: int = 10, session: Optional[Any] = None) -> Dict[str, Any]:
    """Search Coles and return normalised product records."""
    key = query.strip().lower()
    hit = _cached(key)
    if hit is not None:
        return {**hit, "cached": True}

    http = session or requests
    try:
        # Serialised and spaced: concurrent Coles requests are what trips the
        # interstitial, and once tripped it stays tripped for a while.
        global _last_request_at
        with _lock:
            wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
            if wait > 0:
                time.sleep(wait)
            response = http.get(
                SEARCH_URL, params={"q": query}, headers=_HEADERS, timeout=30
            )
            _last_request_at = time.monotonic()
    except Exception as exc:
        return {"status": "error", "query": query, "message": str(exc),
                "products": [], "store": STORE_NAME}

    if response.status_code != 200:
        return {
            "status": "error",
            "query": query,
            "message": f"Coles returned status {response.status_code}",
            "products": [],
            "store": STORE_NAME,
        }

    # A bot challenge returns 200 with a tiny body and no __NEXT_DATA__.
    if len(response.text) < 20_000:
        return {
            "status": "error",
            "query": query,
            "message": "Coles served a challenge page instead of results "
                       "(request rate too high, or blocked).",
            "products": [],
            "store": STORE_NAME,
        }

    raw = _extract_results(response.text)
    products = [normalise(p) for p in raw if isinstance(p, dict) and p.get("pricing")]
    products = [p for p in products if p["name"]][:limit]

    result = {
        "status": "success",
        "query": query,
        "count": len(products),
        "products": products,
        "store": STORE_NAME,
    }
    _remember(key, result)
    return result
