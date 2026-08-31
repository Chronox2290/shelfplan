"""Background top-up of the catalogue, one slow request at a time.

Coles blocks bursts, and the block outlasts whatever caused it. Asking for
forty things when someone presses a button is therefore the worst possible
shape of request -- it is exactly what trips the protection, and it fails at
the moment a person is waiting.

Spreading the same work thinly changes that. One request every couple of
minutes, forever, never looks like a crawl, and the catalogue fills in while
nobody is watching. A blocked store simply pauses and tries again later, and
because the page reads from the local catalogue rather than the store, being
blocked stops mattering.

Off by default. Set TRICKLE=1 to turn it on.
"""

from typing import List
import os
import random
import threading
import time

from src.supermarkets import recipes as recipe_lib

from . import pricing
from .db import SessionLocal

ENABLED = os.getenv("TRICKLE", "0") not in ("0", "false", "False", "")
# Two minutes between requests is roughly a thousandth of what a crawler does
# and has not tripped anything in testing.
INTERVAL_S = max(20, int(os.getenv("TRICKLE_INTERVAL_SECONDS", "120") or 120))
STORES = [s.strip() for s in
          os.getenv("TRICKLE_STORES", "coles,woolworths").split(",") if s.strip()]

_thread: threading.Thread = None
_stop = threading.Event()
_state = {"runs": 0, "added": 0, "skipped": 0, "lastTerm": "", "lastStore": ""}


def _terms() -> List[str]:
    """Search terms worth having in the catalogue.

    The seeder's grocery vocabulary, plus every ingredient the recipe builder
    can actually put on a shopping list -- there is no point holding prices for
    things this app will never suggest.
    """
    terms = list(getattr(__import__(
        "scripts.stock_catalogue", fromlist=["TERMS"]), "TERMS", []))
    terms += [meta["query"] for meta in recipe_lib.INGREDIENTS.values()]
    seen = set()
    return [t for t in terms if not (t.lower() in seen or seen.add(t.lower()))]


def _loop() -> None:
    terms = _terms()
    # Shuffled so a restart does not always re-walk the same opening stretch,
    # and so two instances on one connection do not march in step.
    random.shuffle(terms)
    index = 0

    while not _stop.is_set():
        # Jitter keeps the pattern from looking metronomic.
        wait = INTERVAL_S * random.uniform(0.75, 1.25)
        if _stop.wait(wait):
            return

        term = terms[index % len(terms)]
        index += 1
        store = STORES[index % len(STORES)]

        if not pricing.breaker.allows(store):
            _state["skipped"] += 1
            continue

        try:
            with SessionLocal() as session:
                before = pricing.catalogue_stats(session)["byStore"].get(store, 0)
                result = pricing.search(session, term, limit=36, store=store)
                after = pricing.catalogue_stats(session)["byStore"].get(store, 0)
            _state["runs"] += 1
            _state["added"] += max(0, after - before)
            _state["lastTerm"] = term
            _state["lastStore"] = store
            if result.get("status") != "success":
                _state["skipped"] += 1
        except Exception:  # noqa: BLE001 -- a background job must not die
            _state["skipped"] += 1


def start() -> bool:
    global _thread
    if not ENABLED or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="trickle", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()


def status() -> dict:
    return {
        "enabled": ENABLED,
        "running": bool(_thread and _thread.is_alive()),
        "intervalSeconds": INTERVAL_S,
        "stores": STORES,
        **_state,
    }
