"""One interface over both supermarkets.

Woolworths and Coles are reached very differently -- a JSON search API versus a
server-rendered page -- but both normalise to the same record shape, so
everything above this module can treat them as one catalogue.
"""

from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from . import catalog as woolworths_catalog
from . import coles_catalog
from . import resolve as _resolve

STORES: Dict[str, Callable[..., Dict[str, Any]]] = {
    "woolworths": woolworths_catalog.search,
    "coles": coles_catalog.search,
}

ALL_STORES = tuple(STORES)


def search(
    query: str,
    limit: int = 10,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Search several stores at once and return their results side by side."""
    wanted = [s for s in (stores or ALL_STORES) if s in STORES]
    if not wanted:
        return {"status": "error", "message": "No known store requested.",
                "byStore": {}, "products": []}

    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        results = dict(zip(wanted, pool.map(
            lambda s: STORES[s](query, limit=limit), wanted)))

    products: List[Dict[str, Any]] = []
    for store, result in results.items():
        products.extend(result.get("products") or [])

    # Cheapest comparable line first; rows without a per-kilo basis sink to the
    # bottom rather than pretending to be free.
    products.sort(key=lambda p: (p.get("per_kg") is None, p.get("per_kg") or 0))

    return {
        "status": "success" if any(
            r.get("status") == "success" for r in results.values()) else "error",
        "query": query,
        "byStore": {
            s: {"status": r.get("status"), "count": len(r.get("products") or []),
                "message": r.get("message", "")}
            for s, r in results.items()
        },
        "products": products,
        "count": len(products),
    }


def compare_food(
    food: str,
    query: str,
    target_pack_g: Optional[float] = None,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Price one planned food at every store and say which is cheaper.

    Each store is resolved independently -- pack matching and drained-weight
    handling apply per store -- and only confident matches are eligible to win,
    so a mis-matched product cannot be crowned cheapest.
    """
    wanted = [s for s in (stores or ALL_STORES) if s in STORES]

    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
        resolved = dict(zip(wanted, pool.map(
            lambda s: _resolve.resolve_food(
                food, query, target_pack_g=target_pack_g, store=s), wanted)))

    eligible = [
        r for r in resolved.values()
        if r.get("status") == "ok" and r.get("per_kg") and not r.get("needs_review")
    ]
    best = min(eligible, key=lambda r: r["per_kg"]) if eligible else None

    # Only claim a saving when two stores both produced a confident price.
    saving = None
    if best and len(eligible) > 1:
        dearest = max(eligible, key=lambda r: r["per_kg"])
        if dearest["per_kg"] > best["per_kg"]:
            saving = {
                "perKg": round(dearest["per_kg"] - best["per_kg"], 2),
                "percent": round(
                    (dearest["per_kg"] - best["per_kg"]) / dearest["per_kg"] * 100, 1),
                "against": dearest["store"],
            }

    return {
        "food": food,
        "query": query,
        "byStore": resolved,
        "cheapest": best["store"] if best else None,
        "cheapestPerKg": best["per_kg"] if best else None,
        "saving": saving,
        "comparable": len(eligible),
    }
