"""Re-price everybody's shopping list on the day the specials change.

Prices only ever moved when somebody pressed "Refresh prices", which makes the
history sparse and the "cheapest yet" verdict weak: a run of readings taken
whenever a person happened to open the page says less than one reading a week
taken on the same day.

Woolworths and Coles both start their new specials on **Wednesday**, so that is
the day worth reading. Once a week, in the small hours, every plan's shopping
list gets today's price appended.

Two rules keep this from becoming a nuisance to the stores:

* It reads the **catalogue**, not the shops. Nothing here makes an outbound
  request. Keeping the catalogue itself fresh is the trickle job's business,
  and it is already paced for that.
* A line somebody pinned by hand keeps the product they chose, exactly as a
  manual refresh does.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import os
import threading
import time

from sqlalchemy import select

from src.supermarkets import recipes as recipe_lib, resolve

from . import pricing
from .db import Plan, SessionLocal

ENABLED = os.getenv("AUTO_PRICE", "1") not in ("0", "false", "False", "")
# Wednesday. 0 is Monday, as weekday() counts.
DAY = max(0, min(6, int(os.getenv("AUTO_PRICE_DAY", "2") or 2)))
# Early enough that the new specials are loaded, late enough to be off-peak.
HOUR = max(0, min(23, int(os.getenv("AUTO_PRICE_HOUR", "5") or 5)))
# How stale a reading has to be before it is worth taking another.
MIN_AGE_DAYS = max(1, int(os.getenv("AUTO_PRICE_MIN_AGE_DAYS", "5") or 5))

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_state: Dict[str, Any] = {
    "runs": 0, "plansPriced": 0, "linesPriced": 0, "lastRun": "", "lastError": "",
}


def _seconds_until_next_run(now: datetime) -> float:
    """How long until the next scheduled hour, in the server's own timezone."""
    target = now.replace(hour=HOUR, minute=0, second=0, microsecond=0)
    days_ahead = (DAY - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return max(60.0, (target - now).total_seconds())


def _price_line(session, food: str, meta: Dict[str, Any],
                history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Today's reading for one line, from the catalogue, or nothing."""
    pinned = pricing.pinned_product(session, meta or {})
    today = date.today().isoformat()
    if pinned:
        record = {
            "price": pinned["pack_price"],
            "pack": pinned.get("pack_g") or (meta or {}).get("pack"),
            "date": today, "store": pinned.get("store") or "woolworths",
            "source": "weekly check", "matched": pinned.get("name", ""),
        }
        if pinned.get("url"):
            record["url"] = pinned["url"]
        if pinned.get("on_special"):
            record["onSpecial"] = True
        if pinned.get("was_price"):
            record["wasPrice"] = pinned["was_price"]
        return record

    query = (meta or {}).get("woo") or food
    ingredient = recipe_lib.INGREDIENTS.get(food) or {}
    products = pricing.candidates_for(
        session, food, query, aisle=ingredient.get("aisle", ""))
    if not products:
        return None

    target = (history[-1].get("pack") if history else None) or (meta or {}).get("pack")
    found = resolve.resolve_from_products(food, query, products,
                                          target_pack_g=target)
    if found.get("status") != "ok" or not found.get("price"):
        return None
    # A doubtful *product* is not worth writing into a history somebody reads
    # as fact -- better a gap than a wrong reading. Being sold by the each is
    # not doubt about the product, though, and refusing those meant broccoli,
    # bananas and every other loose vegetable were never priced at all.
    if found.get("mismatch"):
        return None

    record = {
        "price": found["price"], "pack": found.get("pack"), "date": today,
        "store": "Woolworths (online)", "source": "weekly check",
        "matched": found.get("matched_name") or "",
    }
    if found.get("url"):
        record["url"] = found["url"]
    if found.get("on_special"):
        record["onSpecial"] = True
    if found.get("was_price"):
        record["wasPrice"] = found["was_price"]
    return record


def price_everything() -> Dict[str, int]:
    """One pass over every plan. Returns what it did."""
    plans_touched = 0
    lines_touched = 0
    cutoff = (date.today() - timedelta(days=MIN_AGE_DAYS)).isoformat()

    with SessionLocal() as session:
        plan_ids = list(session.scalars(select(Plan.id)))

    for plan_id in plan_ids:
        if _stop.is_set():
            break
        with SessionLocal() as session:
            plan = session.get(Plan, plan_id)
            if plan is None:
                continue
            # Copied a level deeper than looks necessary: `plan.data` is a JSON
            # column, and mutating the loaded value in place also mutates the
            # snapshot SQLAlchemy compares against, so the UPDATE never runs.
            data = dict(plan.data or {})
            shop = {k: dict(v or {}) for k, v in (data.get("shop") or {}).items()}
            prices = {k: list(v or []) for k, v in (data.get("prices") or {}).items()}
            if not shop:
                continue

            changed = 0
            for food, meta in shop.items():
                history = prices.get(food) or []
                if history and history[-1].get("date", "") > cutoff:
                    continue        # priced recently enough already
                record = _price_line(session, food, meta, history)
                if record is None:
                    continue
                if history and history[-1].get("date") == record["date"]:
                    history[-1] = record
                else:
                    history.append(record)
                prices[food] = history
                changed += 1

            if changed:
                data["shop"] = shop
                data["prices"] = prices
                plan.data = data
                # So a page holding an older copy is told, rather than
                # overwriting the reading this just took.
                plan.version = (plan.version or 1) + 1
                session.commit()
                plans_touched += 1
                lines_touched += changed

    return {"plans": plans_touched, "lines": lines_touched}


def _loop() -> None:
    while not _stop.is_set():
        wait = _seconds_until_next_run(datetime.now())
        if _stop.wait(wait):
            return
        try:
            done = price_everything()
            _state["runs"] += 1
            _state["plansPriced"] += done["plans"]
            _state["linesPriced"] += done["lines"]
            _state["lastRun"] = datetime.now(timezone.utc).isoformat()
            _state["lastError"] = ""
        except Exception as exc:  # noqa: BLE001 -- a background job must not die
            _state["lastError"] = str(exc)[:200]
        # A moment's pause so a clock that has not ticked past the hour yet
        # cannot set the same run off twice.
        time.sleep(90)


def start() -> bool:
    global _thread
    if not ENABLED or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="autoprice", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()


def status() -> Dict[str, Any]:
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")
    return {
        "enabled": ENABLED,
        "running": bool(_thread and _thread.is_alive()),
        "day": days[DAY],
        "hour": HOUR,
        "minAgeDays": MIN_AGE_DAYS,
        "nextRunInHours": round(
            _seconds_until_next_run(datetime.now()) / 3600.0, 1),
        **_state,
    }
