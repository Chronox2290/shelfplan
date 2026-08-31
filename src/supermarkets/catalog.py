"""Structured product lookup built on the store search APIs.

The original `woolworths.search_products` returns a bare unit string ("g", "kg")
with no magnitude, and treats `Price` as a pack price. Both are wrong for
variable-weight lines: a fillet listed as "per 350g" carries Price=12 meaning
$12/kg, not $12 for the pack. This module keeps the magnitude and derives the
pack price from the authoritative per-unit price instead.
"""

from typing import Any, Dict, List, Optional
import re

import threading
import time

from . import woolworths

STORE_NAME = "woolworths"

# Woolworths sits behind Akamai, which answers 403 "Access Denied" once it
# decides a caller is a crawler -- and the block is on the address, so it takes
# the whole household out. This module previously had no throttle at all, which
# is how a catalogue seeding run earned one. One request at a time, spaced.
_MIN_INTERVAL_S = 2.5
_lock = threading.Lock()
_last_request_at = 0.0

# The search endpoint accepts a page size up to 36 and answers 400 above that.
MAX_PAGE_SIZE = 36

# "1KG" / "100G" / "1L" / "100ML" / "1EA" -> grams (or ml, treated 1:1) per unit.
_CUP_MEASURE = re.compile(r"^\s*([\d.]+)\s*(KG|G|L|ML|EA|EACH)\s*$", re.I)

# "1.3kg - 1.7kg", "per 350g", "500g", "420g tin", "8 pack"
_SIZE_TOKEN = re.compile(r"([\d.]+)\s*(kg|g|l|ml)\b", re.I)

_TO_GRAMS = {"kg": 1000.0, "g": 1.0, "l": 1000.0, "ml": 1.0}


def _num(value: Any) -> Optional[float]:
    """Coerce to a positive float, or None."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def parse_pack_grams(product: Dict[str, Any]) -> Optional[float]:
    """Best-effort pack size in grams (ml counted 1:1).

    Prefers the API's own gram figure, falls back to parsing the size text.
    A range ("500g - 650g") collapses to its midpoint, which is what a shopper
    actually ends up paying for on average.
    """
    direct = _num(product.get("UnitWeightInGrams"))
    if direct:
        return direct

    text = product.get("PackageSize") or ""
    if not isinstance(text, str):
        return None

    grams = [
        float(n) * _TO_GRAMS[u.lower()]
        for n, u in _SIZE_TOKEN.findall(text)
        if u.lower() in _TO_GRAMS
    ]
    if not grams:
        return None
    # Midpoint of a range; the single value otherwise.
    return (min(grams) + max(grams)) / 2 if len(grams) > 1 else grams[0]


def parse_unit_price_per_kg(product: Dict[str, Any]) -> Optional[float]:
    """Price per kilogram (or per litre), from the API's cup price.

    `CupPrice` is quoted against `CupMeasure` -- usually "1KG" but sometimes
    "100G", which is a 10x difference and the easiest way to get this wrong.
    Per-each lines have no meaningful weight basis, so they return None.
    """
    cup = _num(product.get("CupPrice")) or _num(product.get("InstoreCupPrice"))
    if cup is None:
        return None

    measure = product.get("CupMeasure") or ""
    match = _CUP_MEASURE.match(measure) if isinstance(measure, str) else None
    if not match:
        return None

    qty, unit = float(match.group(1)), match.group(2).lower()
    if unit in ("ea", "each") or qty <= 0:
        return None

    grams = qty * _TO_GRAMS[unit]
    return cup * 1000.0 / grams


# Woolworths files every grocery line under a trading department. What has no
# department is its "Everyday Market" -- a third-party marketplace selling
# books, kitchenware and garden supplies through the same search. That is where
# a search for zucchini returns a cookbook called "Artichoke to Zucchini" and a
# search for mushrooms returns an acrylic ornament. Neither is an ingredient.
_NON_FOOD_DEPARTMENTS = {"GENERAL MERCHANDISE"}


def department_of(product: Dict[str, Any]) -> str:
    extra = product.get("AdditionalAttributes") or {}
    return (extra.get("sapdepartmentname") or "").strip().upper()


def is_grocery(product: Dict[str, Any]) -> bool:
    """Is this something you could put in a meal, rather than merchandise?"""
    department = department_of(product)
    return bool(department) and department not in _NON_FOOD_DEPARTMENTS


def normalise(product: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one raw API product into the fields a meal plan needs."""
    pack_g = parse_pack_grams(product)
    per_kg = parse_unit_price_per_kg(product)
    listed = _num(product.get("Price")) or _num(product.get("InstorePrice"))

    # For a fixed-weight pack, `Price` is the shelf price. For a variable-weight
    # line it is the per-kilo rate, so multiplying the unit price by the pack
    # size is the only figure that stays consistent with `pack`.
    if per_kg is not None and pack_g is not None:
        pack_price = round(per_kg * pack_g / 1000.0, 2)
    else:
        pack_price = round(listed, 2) if listed is not None else None

    # Flag the disagreement rather than silently picking a side.
    variable_weight = bool(
        listed is not None
        and pack_price is not None
        and abs(listed - pack_price) > max(0.05, 0.05 * pack_price)
    )

    was = _num(product.get("WasPrice"))
    return {
        "name": product.get("DisplayName") or product.get("Name") or "",
        "brand": product.get("Brand") or "",
        "stockcode": product.get("Stockcode"),
        "barcode": str(product.get("Barcode") or ""),
        "pack_price": pack_price,
        "pack_g": round(pack_g) if pack_g is not None else None,
        "per_kg": round(per_kg, 2) if per_kg is not None else None,
        "cup_string": product.get("CupString") or "",
        "package_size": product.get("PackageSize") or "",
        "listed_price": round(listed, 2) if listed is not None else None,
        "variable_weight": variable_weight,
        "on_special": bool(product.get("IsOnSpecial")),
        "was_price": round(was, 2) if was is not None else None,
        "in_stock": bool(product.get("IsInStock")),
        "available": bool(product.get("IsAvailable")),
        # SmallImageFile is a 40px thumbnail that looks blurry at any usable
        # size. The medium variant is the same URL with the path swapped, and
        # is ~9 KB rather than ~100 KB for large.
        "image": (product.get("MediumImageFile")
                  or (product.get("SmallImageFile") or "").replace(
                      "/small/", "/medium/")),
        "url": (
            f"https://www.woolworths.com.au/shop/productdetails/"
            f"{product.get('Stockcode')}"
            if product.get("Stockcode")
            else ""
        ),
        "department": department_of(product),
        "store": STORE_NAME,
    }


def _iter_raw_products(payload: Dict[str, Any]):
    """Yield each product from the nested Products-of-Products response."""
    for group in payload.get("Products") or []:
        if not isinstance(group, dict):
            continue
        inner = group.get("Products")
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    yield item
        elif "Stockcode" in group:
            yield group


def search(query: str, limit: int = 10, page: int = 1) -> Dict[str, Any]:
    """Search Woolworths and return normalised product records.

    The endpoint returns ten products unless asked otherwise, while reporting a
    much larger match count. Requesting a page size is what makes a catalogue
    practical: one request can carry 36 products instead of 10, and requests
    are the scarce resource here, not bandwidth.
    """
    global _last_request_at
    try:
        with _lock:
            wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
            if wait > 0:
                time.sleep(wait)
            _last_request_at = time.monotonic()
        response = woolworths.requests.get(
            woolworths.API_URL,
            params={
                "searchTerm": query,
                # 36 is the ceiling: anything larger is rejected with a 400.
                "pageSize": max(1, min(int(limit), MAX_PAGE_SIZE)),
                "pageNumber": max(1, int(page)),
            },
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            },
            timeout=30,
        )
    except Exception as exc:
        return {"status": "error", "query": query, "message": str(exc), "products": []}

    if response.status_code != 200:
        # 4xx other than 429 means the request itself was wrong, which is our
        # fault and not the store refusing us. The distinction matters: the
        # circuit breaker must not take a store offline because of a bug here.
        our_fault = (400 <= response.status_code < 500
                     and response.status_code not in (403, 429))
        blocked = response.status_code in (403, 429)
        message = ("Woolworths is refusing requests from this address. It "
                   "usually lifts within a few hours; indexed prices still "
                   "work in the meantime."
                   if blocked else
                   f"API request failed with status {response.status_code}")
        return {
            "status": "error",
            "query": query,
            "message": message,
            "products": [],
            "clientError": our_fault,
            "blocked": blocked,
        }

    try:
        payload = response.json()
    except ValueError as exc:
        return {"status": "error", "query": query, "message": str(exc), "products": []}

    raw = [p for p in _iter_raw_products(payload) if is_grocery(p)]
    products = [normalise(p) for p in raw]
    products = [p for p in products if p["name"]][:limit]
    return {
        "status": "success",
        "query": query,
        "count": len(products),
        "products": products,
        "available": payload.get("SearchResultsCount"),
        "page": page,
    }
