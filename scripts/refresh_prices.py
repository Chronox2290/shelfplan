"""Refresh the Shelf Plan's price block from live Woolworths data.

Reads the plan's embedded state, re-prices every shopping item that already has
a recorded price, and appends a dated record to that food's history. Existing
records are never rewritten -- the plan keeps its price history, and a bad match
can be rolled back by dropping the newest entry.

Usage:
    uv run python scripts/refresh_prices.py PLAN.html [-o OUT.html] [--store NAME]
    uv run python scripts/refresh_prices.py PLAN.html --dry-run
"""

from typing import Any, Dict, List, Tuple
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.supermarkets import resolve  # noqa: E402

STATE_RE = re.compile(
    r'(<script[^>]*id="state"[^>]*>)(.*?)(</script>)', re.S)


def load_state(html: str) -> Dict[str, Any]:
    match = STATE_RE.search(html)
    if not match:
        raise SystemExit("no <script id=\"state\"> block found in that file")
    return json.loads(match.group(2))


def write_state(html: str, state: Dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=False, indent=1)
    # A literal </script> inside the JSON would close the tag early.
    payload = payload.replace("</", "<\\/")
    return STATE_RE.sub(
        lambda m: m.group(1) + payload + m.group(3), html, count=1)


def refresh(state: Dict[str, Any], store: str) -> Tuple[List[dict], List[dict]]:
    """Re-price every shopping item that already carries a price record."""
    shop = state.get("shop", {})
    prices = state.get("prices", {})
    today = date.today().isoformat()

    applied: List[dict] = []
    skipped: List[dict] = []

    for food, meta in shop.items():
        history = prices.get(food)
        if not history:
            continue

        latest = history[-1]
        result = resolve.resolve_food(
            food=food,
            query=(meta or {}).get("woo") or food,
            target_pack_g=latest.get("pack"),
        )

        if result["status"] != "ok" or result.get("needs_review"):
            result["previous"] = latest
            skipped.append(result)
            continue
        if result.get("price") is None or not result.get("pack"):
            result["previous"] = latest
            skipped.append(result)
            continue

        record = {
            "price": result["price"],
            "pack": result["pack"],
            "date": today,
            "store": store,
            "source": "woolworths-api",
            "matched": result["matched_name"],
        }
        if result.get("stockcode"):
            record["stockcode"] = result["stockcode"]
        if result.get("on_special"):
            record["onSpecial"] = True

        # Don't stack an identical record on top of today's entry.
        if latest.get("date") == today and latest.get("price") == record["price"]:
            skipped.append({**result, "previous": latest,
                            "review_reasons": ["already recorded today"]})
            continue

        history.append(record)
        result["previous"] = latest
        applied.append(result)

    return applied, skipped


def per_kg(entry: Dict[str, Any]) -> Any:
    if not entry or not entry.get("pack"):
        return None
    return entry["price"] / (entry["pack"] / 1000.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Path to the plan HTML file")
    parser.add_argument("-o", "--out", help="Where to write the updated HTML")
    parser.add_argument("--store", default="Woolworths (online)",
                        help="Store label recorded against new prices")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args()

    html = Path(args.plan).read_text(encoding="utf-8")
    state = load_state(html)
    applied, skipped = refresh(state, args.store)

    print(f"updated {len(applied)} foods, held back {len(skipped)}\n")
    if applied:
        print(f'{"food":36} {"was":>9} {"now":>9} {"delta":>8}')
        print("-" * 66)
        for r in sorted(applied, key=lambda x: x["food"]):
            was = per_kg(r.get("previous"))
            now = r.get("per_kg")
            delta = f"{(now - was) / was * 100:+6.1f}%" if was and now else ""
            print(f'{r["food"][:34]:36} '
                  f'{("$%.2f" % was) if was else "-":>9} '
                  f'{("$%.2f" % now) if now else "-":>9} {delta:>8}')

    if skipped:
        print(f"\nheld back for review:")
        for r in skipped:
            why = "; ".join(r.get("review_reasons") or [r.get("message", "?")])
            print(f'  {r["food"][:38]:40} {why}')
            if r.get("matched_name"):
                print(f'  {"":40} matched: {r["matched_name"][:52]}')

    if args.dry_run:
        print("\ndry run -- nothing written")
        return

    out = Path(args.out or args.plan)
    out.write_text(write_state(html, state), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
