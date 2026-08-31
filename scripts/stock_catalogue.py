"""Fill the local product catalogue by searching common grocery terms.

The supermarkets publish no bulk export, so there is no way to simply download
their database. This walks a list of everyday search terms instead and keeps
whatever comes back -- a few hundred terms yields a few thousand products,
which covers ordinary shopping well.

It is deliberately slow. Coles blocks bursts and the block outlasts the burst
that caused it, so the pace here is set by what the stores tolerate, not by how
fast the machine could go.

    uv run python scripts/stock_catalogue.py                # everything
    uv run python scripts/stock_catalogue.py --store woolworths
    uv run python scripts/stock_catalogue.py --terms 40 --delay 3
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp import pricing  # noqa: E402
from webapp.db import SessionLocal, init_db  # noqa: E402

# Everyday shopping vocabulary. Broad terms return many products each, which is
# a far better yield per request than chasing individual brands.
TERMS = [
    # meat and seafood
    "chicken breast", "chicken thigh", "chicken mince", "whole chicken",
    "beef mince", "beef steak", "rump steak", "diced beef", "lamb chops",
    "pork loin", "pork chops", "bacon", "ham", "sausages", "salmon fillet",
    "tuna", "prawns", "white fish", "barramundi",
    # dairy and fridge
    "milk", "lactose free milk", "cheese", "tasty cheese", "parmesan",
    "yoghurt", "greek yoghurt", "protein yoghurt", "butter", "margarine",
    "cream", "sour cream", "cottage cheese", "eggs", "tofu",
    # produce
    "banana", "apple", "orange", "lemon", "avocado", "berries", "grapes",
    "tomato", "potato", "sweet potato", "onion", "garlic", "carrot",
    "broccoli", "cauliflower", "capsicum", "zucchini", "mushroom", "spinach",
    "lettuce", "cucumber", "green beans", "peas", "corn", "pumpkin",
    # pantry staples
    "rice", "brown rice", "basmati rice", "pasta", "spaghetti", "penne",
    "noodles", "couscous", "quinoa", "rolled oats", "muesli", "cereal",
    "bread", "wraps", "tortilla", "flour", "sugar", "honey",
    "olive oil", "vegetable oil", "vinegar", "salt", "pepper", "spices",
    "stock cubes", "tomato passata", "tinned tomatoes", "tomato paste",
    "baked beans", "chickpeas", "kidney beans", "lentils", "coconut milk",
    "curry paste", "soy sauce", "peanut butter", "jam", "vegemite",
    "tuna tins", "salmon tins", "crackers", "nuts", "almonds", "cashews",
    # freezer
    "frozen vegetables", "frozen peas", "frozen berries", "frozen chips",
    "frozen fish", "ice cream", "frozen pizza",
    # household and drinks
    "coffee", "tea", "juice", "sparkling water", "protein powder",
    "toilet paper", "paper towel", "dishwashing liquid", "laundry powder",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("woolworths", "coles"),
                        help="Only this store. Default is both.")
    parser.add_argument("--terms", type=int, default=len(TERMS),
                        help="How many search terms to run.")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds between requests. Lower is riskier.")
    parser.add_argument("--limit", type=int, default=36,
                        help="Products per search. Woolworths caps this at 36.")
    parser.add_argument("--start", type=int, default=0,
                        help="Skip this many terms -- resume a stopped run.")
    args = parser.parse_args()

    init_db()
    which = [args.store] if args.store else ["woolworths", "coles"]
    todo = TERMS[args.start:args.start + args.terms]

    print(f"Stocking the catalogue from {len(todo)} terms "
          f"across {', '.join(which)}.")
    print(f"About {len(todo) * len(which) * args.delay / 60:.0f} minutes at "
          f"{args.delay}s between requests.\n")

    added_total = 0
    blocked = {s: 0 for s in which}

    with SessionLocal() as session:
        before = dict(pricing.catalogue_stats(session)["byStore"])
        for index, term in enumerate(todo, start=1):
            for store in which:
                if blocked[store] >= 3:
                    continue  # give up on a store that keeps refusing
                result = pricing.search(session, term, limit=args.limit,
                                        store=store, force=False)
                if result.get("status") != "success":
                    blocked[store] += 1
                    print(f"  [{index:3}/{len(todo)}] {term:22} {store:11} "
                          f"blocked ({blocked[store]}/3)")
                    continue
                found = result.get("products") or []
                # pricing.search has already stored these; measure the real
                # growth rather than re-inserting and always reporting zero.
                after = pricing.catalogue_stats(session)["byStore"].get(store, 0)
                added = after - before.get(store, 0)
                before[store] = after
                added_total += added
                mark = "cached" if result.get("cached") else "fetched"
                avail = result.get("available")
                print(f"  [{index:3}/{len(todo)}] {term:22} {store:11} "
                      f"{len(found):3} seen"
                      + (f" of {avail:>4}" if avail else "        ")
                      + f", {added:3} new  ({mark})")
                if not result.get("cached"):
                    time.sleep(args.delay)

        stats = pricing.catalogue_stats(session)

    print(f"\nAdded {added_total} new products.")
    print(f"Catalogue now holds {stats['total']} products: "
          + ", ".join(f"{k} {v}" for k, v in stats["byStore"].items()))
    for store, count in blocked.items():
        if count >= 3:
            print(f"Gave up on {store} after {count} refusals. "
                  f"Try again in half an hour.")


if __name__ == "__main__":
    main()
