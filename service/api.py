"""Local HTTP price service for the meal plan.

Run:  uv run uvicorn service.api:app --port 8000

Serves JSON on the same shape the plan's `prices` block already uses, so a
refreshed record can be dropped straight in. CORS is wide open because this
binds to localhost and is meant to be reachable from a page opened off disk.
"""

from typing import Any, Dict, List, Optional
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.supermarkets import catalog, resolve  # noqa: E402

app = FastAPI(title="Shelf Plan price service", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class FoodRequest(BaseModel):
    food: str
    query: Optional[str] = None
    pack: Optional[float] = None


class BatchRequest(BaseModel):
    items: List[FoodRequest]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "stores": ["woolworths"]}


@app.get("/search")
def search(
    q: str = Query(..., description="Product search term"),
    limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Raw normalised search results, with pack size and per-kg price."""
    return catalog.search(q, limit=limit)


@app.get("/price")
def price(
    food: str = Query(..., description="Planned food name"),
    query: Optional[str] = Query(None, description="Store search term"),
    pack: Optional[float] = Query(None, description="Planned pack size in grams"),
) -> Dict[str, Any]:
    """One food, priced on the plan's own basis."""
    return resolve.resolve_food(food, query or food, target_pack_g=pack)


@app.post("/prices")
def prices(request: BatchRequest) -> Dict[str, Any]:
    """Price a whole shopping list in one call.

    Splits the results so a caller can apply the confident ones and leave the
    rest for a human, rather than overwriting checked figures with guesses.
    """
    resolved = [
        resolve.resolve_food(item.food, item.query or item.food, target_pack_g=item.pack)
        for item in request.items
    ]
    ok = [r for r in resolved if r["status"] == "ok"]
    return {
        "count": len(resolved),
        "auto": [r for r in ok if not r.get("needs_review")],
        "review": [r for r in ok if r.get("needs_review")],
        "failed": [r for r in resolved if r["status"] != "ok"],
    }
