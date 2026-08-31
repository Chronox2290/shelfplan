"""Shared price cache and a circuit breaker for the supermarkets.

Every lookup leaves from this server's address, so upstream load scales with
the number of *people* using the app unless something sits in between. Two
things do:

* **A shared cache in the database.** Keyed by store and search term, not by
  user, so ten households looking up "rolled oats" cost one request rather than
  ten. It survives restarts, which the in-process cache did not.
* **A circuit breaker.** Coles answers a burst with a challenge page, and
  retrying through that block extends it. After a few failures the breaker
  opens and stops calling out entirely for a cooling-off period, serving cached
  prices instead.

When the breaker is open or a fetch fails, a stale entry is served rather than
nothing, tagged with its age. A week-old price labelled "as of last Tuesday" is
far more useful for planning than an empty cell -- but it is always labelled,
never passed off as today's.
"""

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional
import os
import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.supermarkets import coles_catalog, resolve, stores
from src.supermarkets import catalog as woolworths_catalog

from .db import PriceCache, Product, utcnow

# Supermarket shelf prices move daily at most, and usually weekly.
CACHE_HOURS = max(1, int(os.getenv("PRICE_CACHE_HOURS", "12") or 12))
# How old a cached answer may be before it is withheld entirely.
STALE_LIMIT_HOURS = max(CACHE_HOURS, int(os.getenv("PRICE_STALE_HOURS", "168") or 168))

_FAILURES_BEFORE_OPEN = max(1, int(os.getenv("BREAKER_FAILURES", "3") or 3))
_COOLDOWN_MINUTES = max(1, int(os.getenv("BREAKER_COOLDOWN_MINUTES", "20") or 20))

_FETCHERS = {
    "woolworths": lambda q, limit: woolworths_catalog.search(q, limit=limit),
    # Coles renders a whole page of results at once, so it needs no paging.
    "coles": lambda q, limit: coles_catalog.search(q, limit=limit),
}


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------

class _Breaker:
    """Stops calling a store that is refusing us, so the block can lapse."""

    def __init__(self) -> None:
        self._failures: Dict[str, int] = {}
        self._open_until: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def allows(self, store: str) -> bool:
        with self._lock:
            until = self._open_until.get(store)
            if until is None:
                return True
            if datetime.now(timezone.utc) >= until:
                # Half-open: let one request through to test the water.
                del self._open_until[store]
                self._failures[store] = _FAILURES_BEFORE_OPEN - 1
                return True
            return False

    def record_success(self, store: str) -> None:
        with self._lock:
            self._failures.pop(store, None)
            self._open_until.pop(store, None)

    def record_failure(self, store: str) -> None:
        with self._lock:
            count = self._failures.get(store, 0) + 1
            self._failures[store] = count
            if count >= _FAILURES_BEFORE_OPEN:
                self._open_until[store] = (
                    datetime.now(timezone.utc) + timedelta(minutes=_COOLDOWN_MINUTES))

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            return {
                store: {
                    "open": True,
                    "retryInSeconds": max(0, int((until - now).total_seconds())),
                }
                for store, until in self._open_until.items()
            }

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._open_until.clear()


breaker = _Breaker()


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def _key(query: str) -> str:
    return " ".join((query or "").strip().lower().split())[:240]


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _age_hours(row: PriceCache) -> float:
    delta = datetime.now(timezone.utc) - _aware(row.fetched_at)
    return delta.total_seconds() / 3600.0


def _read(session: Session, store: str, query: str) -> Optional[PriceCache]:
    return session.scalar(
        select(PriceCache).where(
            PriceCache.store == store, PriceCache.query_key == _key(query)
        )
    )


def remember_products(session: Session, store: str,
                      products: List[Dict[str, Any]]) -> int:
    """Fold search results into the permanent catalogue.

    Upserts on (store, stockcode) so re-seeing a product refreshes its price
    and keeps its original first_seen. Rows are never deleted here: a product
    that stops appearing in search is still worth having a record of.
    """
    added = 0
    for item in products:
        code = str(item.get("stockcode") or "").strip()
        name = (item.get("name") or "").strip()
        if not code or not name:
            continue
        row = session.scalar(
            select(Product).where(Product.store == store,
                                  Product.stockcode == code))
        if row is None:
            row = Product(store=store, stockcode=code)
            session.add(row)
            added += 1
        row.name = name[:300]
        row.search_key = name.lower()[:300]
        row.barcode = str(item.get("barcode") or "")[:20]
        row.brand = (item.get("brand") or "")[:120]
        row.package_size = (item.get("package_size") or "")[:80]
        row.pack_g = item.get("pack_g")
        row.pack_price = item.get("pack_price")
        row.per_kg = item.get("per_kg")
        row.cup_string = (item.get("cup_string") or "")[:80]
        row.on_special = bool(item.get("on_special"))
        row.was_price = item.get("was_price")
        row.department = (item.get("department") or "")[:60]
        row.in_stock = bool(item.get("in_stock", True))
        row.url = (item.get("url") or "")[:400]
        row.image = (item.get("image") or "")[:400]
        row.last_seen = utcnow()
    session.commit()
    return added


def _write(session: Session, store: str, query: str,
           products: List[Dict[str, Any]]) -> None:
    row = _read(session, store, query)
    if row is None:
        row = PriceCache(store=store, query_key=_key(query))
        session.add(row)
    row.products = products
    row.fetched_at = utcnow()
    session.commit()


def search(session: Session, query: str, limit: int = 10,
           store: str = "woolworths", force: bool = False) -> Dict[str, Any]:
    """One store's results for one query, cached and breaker-guarded."""
    fetcher = _FETCHERS.get(store)
    if fetcher is None:
        return {"status": "error", "store": store, "products": [],
                "message": f"Unknown store {store!r}."}

    row = _read(session, store, query)
    if row is not None and not force:
        age = _age_hours(row)
        if age < CACHE_HOURS:
            return {"status": "success", "store": store, "query": query,
                    "products": (row.products or [])[:limit],
                    "count": min(limit, len(row.products or [])),
                    "cached": True, "ageHours": round(age, 1), "stale": False}

    if not breaker.allows(store):
        return _stale_or_empty(row, store, query, limit,
                              "Paused: that store is rate-limiting us.")

    result = fetcher(query, limit)
    if result.get("status") == "success":
        breaker.record_success(store)
        found = result.get("products") or []
        _write(session, store, query, found)
        # Everything seen goes into the catalogue, not just what was asked for.
        try:
            remember_products(session, store, found)
        except Exception:  # noqa: BLE001 -- the lookup still succeeded
            session.rollback()
        return {**result, "cached": False, "ageHours": 0.0, "stale": False}

    # Only count this against the store if the store actually refused us. A
    # malformed request on our side is a bug to fix, not a reason to stop
    # talking to them for twenty minutes.
    if not result.get("clientError"):
        breaker.record_failure(store)
    return _stale_or_empty(row, store, query, limit,
                           result.get("message", "lookup failed"))


def _stale_or_empty(row: Optional[PriceCache], store: str, query: str,
                    limit: int, reason: str) -> Dict[str, Any]:
    """Serve an old answer, clearly labelled, rather than nothing."""
    if row is not None:
        age = _age_hours(row)
        if age <= STALE_LIMIT_HOURS and row.products:
            return {
                "status": "success", "store": store, "query": query,
                "products": (row.products or [])[:limit],
                "count": min(limit, len(row.products or [])),
                "cached": True, "stale": True, "ageHours": round(age, 1),
                "message": f"{reason} Showing prices from "
                           f"{_describe_age(age)}.",
            }
    return {"status": "error", "store": store, "query": query,
            "products": [], "cached": False, "stale": False,
            "message": reason}


def _describe_age(hours: float) -> str:
    if hours < 1:
        return "the last hour"
    if hours < 24:
        return f"{int(hours)} hours ago"
    days = int(hours // 24)
    return "yesterday" if days == 1 else f"{days} days ago"


def search_all(session: Session, query: str, limit: int = 10,
               store_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Cached search across stores, shaped like stores.search."""
    wanted = [s for s in (store_names or stores.ALL_STORES) if s in _FETCHERS]
    results = {s: search(session, query, limit, s) for s in wanted}

    products: List[Dict[str, Any]] = []
    for result in results.values():
        products.extend(result.get("products") or [])
    products.sort(key=lambda p: (p.get("per_kg") is None, p.get("per_kg") or 0))

    return {
        "status": "success" if any(
            r.get("status") == "success" for r in results.values()) else "error",
        "query": query,
        "byStore": {
            s: {"status": r.get("status"), "count": len(r.get("products") or []),
                "cached": r.get("cached"), "stale": r.get("stale"),
                "ageHours": r.get("ageHours"), "message": r.get("message", "")}
            for s, r in results.items()
        },
        "products": products,
        "count": len(products),
    }


def compare_food(session: Session, food: str, query: str,
                 target_pack_g: Optional[float] = None,
                 store_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Cross-store comparison built on the cache rather than live requests."""
    wanted = [s for s in (store_names or stores.ALL_STORES) if s in _FETCHERS]

    resolved: Dict[str, Any] = {}
    for store in wanted:
        found = search(session, query, limit=12, store=store)
        if found.get("status") != "success" or not found.get("products"):
            resolved[store] = {
                "food": food, "query": query, "status": "not_found",
                "store": store, "message": found.get("message", "no products"),
            }
            continue
        # Reuse the resolver's ranking and basis logic on cached candidates.
        record = resolve.resolve_from_products(
            food, query, found["products"], target_pack_g=target_pack_g)
        record["store"] = store
        record["cached"] = found.get("cached")
        record["stale"] = found.get("stale")
        record["ageHours"] = found.get("ageHours")
        resolved[store] = record

    eligible = [
        r for r in resolved.values()
        if r.get("status") == "ok" and r.get("per_kg") and not r.get("needs_review")
    ]
    best = min(eligible, key=lambda r: r["per_kg"]) if eligible else None

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
        "food": food, "query": query, "byStore": resolved,
        "cheapest": best["store"] if best else None,
        "cheapestPerKg": best["per_kg"] if best else None,
        "saving": saving, "comparable": len(eligible),
    }


def cache_status(session: Session) -> Dict[str, Any]:
    """What the cache holds and whether any store is currently paused."""
    rows = session.scalars(select(PriceCache)).all()
    per_store: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        entry = per_store.setdefault(row.store, {"entries": 0, "oldestHours": 0.0})
        entry["entries"] += 1
        entry["oldestHours"] = max(entry["oldestHours"], round(_age_hours(row), 1))
    return {
        "cacheHours": CACHE_HOURS,
        "staleLimitHours": STALE_LIMIT_HOURS,
        "byStore": per_store,
        "paused": breaker.status(),
    }


def candidates_for(session: Session, food: str, query: str,
                   aisle: str = "", store: str = "woolworths",
                   limit: int = 24) -> List[Dict[str, Any]]:
    """Products worth considering for one ingredient, from the catalogue.

    One place, because there are four callers and they were drifting. The
    pack-size fix went into the price table and not into the weekly check or
    the swap sheet, so the weekly check would have quietly re-matched polenta
    to the dearer corn meal every Wednesday -- a fix applied where somebody
    happened to notice the symptom rather than where the cause was.

    Two things it does that a plain search does not:

    * Takes the pack size out of the query first. The catalogue matches on
      every word, so "Polenta 500g" can only ever find labels that repeat it,
      and the 750g bag never becomes a candidate at all.
    * Prefers the right department for fresh produce. "Mutti Whole Cherry
      Tomatoes" does not say tinned anywhere in its name, and the department
      is the only thing that reliably knows.
    """
    unsized = " ".join(
        word for word in (query or "").split()
        if not re.match(r"^\d+(?:\.\d+)?(?:g|kg|ml|l|pk)?$", word, re.I)
        and word.lower() not in ("pack", "tin", "tins", "jar"))
    plain = (food or "").split(",")[0]

    seen, terms = set(), []
    for term in (unsized, plain, " ".join(plain.split()[:2]), query):
        term = (term or "").strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)

    products: List[Dict[str, Any]] = []
    for term in terms:
        products = catalogue_search(
            session, query=term, store=store, limit=limit).get("products") or []
        products = [p for p in products if is_edible(p)]
        if products:
            break

    if aisle == "produce":
        # Only when some candidate actually carries a department, so a
        # catalogue recorded before departments were stored behaves as before.
        fresh = [p for p in products
                 if (p.get("department") or "").upper() == "FRUIT AND VEG"]
        if fresh:
            products = fresh
    return products


def is_edible(product: Dict[str, Any]) -> bool:
    """Keep merchandise out of anything offering products as food.

    Woolworths sells books, kitchenware and soft toys through the same search
    as its groceries, under an "Everyday Market" that files nothing under a
    trading department. The live catalogue drops those on the way in, but rows
    indexed before departments were recorded have no department to judge, so
    those fall back to the name -- which is how a "Bananas in Pyjamas ... Soft
    Toy Plush" came to be offered as a substitute for bananas.
    """
    department = (product.get("department") or "").upper()
    if department in woolworths_catalog._NON_FOOD_DEPARTMENTS:
        return False
    return not woolworths_catalog.looks_like_merchandise(product.get("name") or "")


def pinned_product(session: Session,
                   meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The exact product a shopping line was pointed at, if it was.

    A line only counts as pinned when somebody chose it: `pinned` carries the
    name they picked, and `stockcode` says which product. Matching on stockcode
    alone would also catch lines the resolver happened to fill in, and those
    should keep being re-resolved.
    """
    if not meta.get("pinned") or not meta.get("stockcode"):
        return None
    row = session.scalars(
        select(Product).where(Product.stockcode == str(meta["stockcode"]))
    ).first()
    if row is None or row.pack_price is None:
        return None
    return {
        "name": row.name, "pack_price": row.pack_price, "pack_g": row.pack_g,
        "per_kg": row.per_kg, "on_special": row.on_special,
        "was_price": row.was_price, "url": row.url, "image": row.image,
        "store": row.store, "stockcode": row.stockcode,
    }


def catalogue_search(
    session: Session,
    query: str = "",
    store: Optional[str] = None,
    on_special: bool = False,
    sort: str = "relevance",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Search the local catalogue. Never touches the network.

    Every word must appear somewhere in the name, which behaves the way people
    expect ("free range eggs" should not match every product containing "free").
    """
    stmt = select(Product)
    if store:
        stmt = stmt.where(Product.store == store)
    if on_special:
        stmt = stmt.where(Product.on_special.is_(True))
    for word in (query or "").lower().split():
        stmt = stmt.where(Product.search_key.like(f"%{word}%"))

    if sort == "cheapest":
        stmt = stmt.order_by(Product.per_kg.is_(None), Product.per_kg)
    elif sort == "dearest":
        stmt = stmt.order_by(Product.per_kg.is_(None), Product.per_kg.desc())
    elif sort == "name":
        stmt = stmt.order_by(Product.search_key)
    else:
        # Shortest name first: the plainest product for a term is usually the
        # one someone means, and variants carry extra words.
        stmt = stmt.order_by(func.length(Product.name), Product.search_key)

    total = session.scalar(
        select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "products": [
            {
                "id": r.id, "store": r.store, "stockcode": r.stockcode,
                "barcode": r.barcode,
                "name": r.name, "brand": r.brand,
                "package_size": r.package_size, "pack_g": r.pack_g,
                "pack_price": r.pack_price, "per_kg": r.per_kg,
                "cup_string": r.cup_string, "on_special": r.on_special,
                "was_price": r.was_price, "department": r.department,
                "in_stock": r.in_stock, "url": r.url, "image": r.image,
                "lastSeen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ],
    }


def catalogue_stats(session: Session) -> Dict[str, Any]:
    """How much of a catalogue has accumulated so far."""
    rows = session.execute(
        select(Product.store, func.count(Product.id))
        .group_by(Product.store)).all()
    specials = session.scalar(
        select(func.count(Product.id)).where(Product.on_special.is_(True))) or 0
    return {
        "byStore": {store: count for store, count in rows},
        "total": sum(c for _, c in rows),
        "onSpecial": specials,
    }


def by_barcode(session: Session, code: str) -> Optional[Dict[str, Any]]:
    """A product already in the catalogue, found by its barcode."""
    from .db import Product
    row = session.scalar(select(Product).where(Product.barcode == code))
    if row is None:
        return None
    return {
        "id": row.id, "store": row.store, "stockcode": row.stockcode,
        "barcode": row.barcode, "name": row.name, "brand": row.brand,
        "package_size": row.package_size, "pack_g": row.pack_g,
        "pack_price": row.pack_price, "per_kg": row.per_kg,
        "cup_string": row.cup_string, "on_special": row.on_special,
        "was_price": row.was_price, "department": row.department,
        "in_stock": row.in_stock, "url": row.url, "image": row.image,
    }
