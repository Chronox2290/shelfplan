"""Turn a scanned barcode into a product.

Three places are tried, in this order, because they answer different questions:

1. **The local catalogue.** Instant, and works while a store is blocking us.
2. **Woolworths search.** Their search accepts a barcode directly and returns
   the exact product, with the current price.
3. **Open Food Facts.** An openly licensed database of packaged food. It has no
   price, but it usually has the nutrition panel -- which is the part a
   supermarket listing most often lacks.

A scan that finds nothing is reported plainly rather than guessed at.
"""

from typing import Any, Dict, Optional
import re

import requests

from . import catalog

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{}.json"
OFF_FIELDS = ("product_name,brands,quantity,nutriments,image_small_url,"
              "serving_quantity,categories_tags")

# Identify ourselves properly: Open Food Facts asks callers to say who they are,
# and an honest agent string is the price of using a free public database.
_HEADERS = {"User-Agent": "ShelfPlan/1.0 (self-hosted meal planner)"}

_SIZE = re.compile(r"([\d.]+)\s*(kg|g|l|ml)\b", re.I)
_TO_GRAMS = {"kg": 1000.0, "g": 1.0, "l": 1000.0, "ml": 1.0}


def valid(code: str) -> bool:
    """A plausible EAN/UPC. Rejects obvious rubbish before any lookup."""
    digits = re.sub(r"\D", "", code or "")
    return 6 <= len(digits) <= 14


def normalise(code: str) -> str:
    return re.sub(r"\D", "", code or "")


def _grams_from(text: str) -> Optional[float]:
    match = _SIZE.search(text or "")
    if not match:
        return None
    return float(match.group(1)) * _TO_GRAMS[match.group(2).lower()]


def from_woolworths(code: str) -> Optional[Dict[str, Any]]:
    """Ask Woolworths for the barcode directly."""
    found = catalog.search(code, limit=5)
    if found.get("status") != "success":
        return None
    for product in found.get("products") or []:
        # Their search is fuzzy, so confirm the barcode actually matches rather
        # than trusting the first result.
        if str(product.get("barcode") or "") == code:
            return product
    products = found.get("products") or []
    return products[0] if len(products) == 1 else None


def from_open_food_facts(code: str) -> Optional[Dict[str, Any]]:
    """Nutrition from the open database, when the store has none."""
    try:
        response = requests.get(OFF_URL.format(code), params={"fields": OFF_FIELDS},
                                headers=_HEADERS, timeout=15)
        payload = response.json()
    except Exception:  # noqa: BLE001
        return None
    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    nutriments = product.get("nutriments") or {}

    def num(key):
        value = nutriments.get(key)
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    name = " ".join(filter(None, [
        (product.get("brands") or "").split(",")[0].strip(),
        product.get("product_name") or "",
    ])).strip()

    return {
        "name": name or "Unnamed product",
        "brand": (product.get("brands") or "").split(",")[0].strip(),
        "barcode": code,
        "package_size": product.get("quantity") or "",
        "pack_g": _grams_from(product.get("quantity") or ""),
        "image": product.get("image_small_url") or "",
        "nutrition": {
            "kcal": num("energy-kcal_100g"),
            "p": num("proteins_100g"),
            "c": num("carbohydrates_100g"),
            "f": num("fat_100g"),
            "fb": num("fiber_100g"),
            "sugar": num("sugars_100g"),
            "salt": num("salt_100g"),
        },
        "store": "",
        "source": "openfoodfacts",
    }


def look_up(code: str) -> Dict[str, Any]:
    """Everything known about a scanned code, and where it came from."""
    code = normalise(code)
    if not valid(code):
        return {"status": "error", "barcode": code,
                "message": "That is not a readable barcode."}

    store_product = from_woolworths(code)
    nutrition = from_open_food_facts(code)

    if store_product is None and nutrition is None:
        return {
            "status": "not_found", "barcode": code,
            "message": ("Not at Woolworths and not in the open food database. "
                        "Add it by name instead."),
        }

    # A store listing gives price and pack; Open Food Facts gives the nutrition
    # panel. Neither is complete on its own, so both are returned.
    return {
        "status": "success",
        "barcode": code,
        "product": store_product,
        "nutrition": nutrition,
        "sources": [s for s, present in
                    (("woolworths", store_product), ("openfoodfacts", nutrition))
                    if present],
    }
