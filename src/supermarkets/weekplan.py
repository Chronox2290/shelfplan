"""Fill a whole week against daily targets, and rebalance a changed meal.

Two jobs that people actually do:

* **Plan the week.** Given "under 2000 kcal, at least 150g protein, at least
  25g fibre, every day", choose meals that satisfy that. Each day is a small
  packing problem: the calorie ceiling is the capacity and the protein and
  fibre floors are what has to be carried.

* **Rebalance one meal.** Having decided on less of something, say how much
  more of something else restores the target. Answering "50g fewer kidney
  beans, so how much more chicken" is a division, but doing it in your head
  over five ingredients is why nobody bothers.
"""

from typing import Any, Dict, List, Optional, Sequence

from . import recipes as recipe_lib


def _macros(recipe: Dict[str, Any], servings: float = 1.0) -> Dict[str, float]:
    per = recipe.get("perServing") or {}
    return {k: (per.get(k) or 0.0) * servings
            for k in ("kcal", "p", "c", "f", "fb")}


def _shortfall(total: Dict[str, float], goals: Dict[str, float]) -> Dict[str, float]:
    return {
        "p": max(0.0, goals["floorP"] - total["p"]),
        "fb": max(0.0, goals["floorF"] - total["fb"]),
        "kcal": goals["ceiling"] - total["kcal"],   # headroom, may go negative
    }


def _fit_score(candidate: Dict[str, float], gap: Dict[str, float]) -> float:
    """How well one meal closes what the day still needs.

    Value is credit for protein and fibre still wanted -- capped, so a meal
    carrying far more protein than the day needs does not beat a balanced one
    -- divided by the calories it spends getting there. That is the whole
    trade-off in one number.
    """
    if candidate["kcal"] <= 0:
        return 0.0
    protein_value = min(candidate["p"], gap["p"]) if gap["p"] > 0 else candidate["p"] * 0.15
    fibre_value = min(candidate["fb"], gap["fb"]) if gap["fb"] > 0 else candidate["fb"] * 0.15
    # Protein is usually the harder floor to reach, so it weighs more.
    return (protein_value * 2.0 + fibre_value * 1.4) / (candidate["kcal"] / 100.0)


def sittings_for(meals_per_day: int) -> List[str]:
    """The distinct sittings a day of this length has, in order."""
    seen, out = set(), []
    for name in _sittings(meals_per_day):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def recipe_suits(recipe: Dict[str, Any], sitting: Optional[str]) -> bool:
    """Does this dish belong at that sitting?

    A recipe with nothing recorded predates meal slots, or was written by hand.
    Treating it as a main is the safer reading: an unlabelled dish is far more
    likely to be a dinner than a bowl of porridge.
    """
    if not sitting:
        return True
    listed = recipe.get("meals") or (
        [recipe["meal"]] if recipe.get("meal") else None)
    return sitting in (listed or ("lunch", "dinner"))


def _sittings(meals_per_day: int) -> List[str]:
    """Name the sittings in a day of this length.

    One meal is dinner; two are lunch and dinner; three are the obvious three.
    Beyond that the extras are snacks between lunch and dinner, which in this
    model means anything a lunch would allow.
    """
    if meals_per_day <= 1:
        return ["dinner"]
    if meals_per_day == 2:
        return ["lunch", "dinner"]
    extra = meals_per_day - 3
    return ["breakfast", "lunch"] + ["lunch"] * extra + ["dinner"]


def plan_week(
    library: Sequence[Dict[str, Any]],
    goals: Dict[str, float],
    days: int = 7,
    meals_per_day: int = 3,
    max_repeats: int = 3,
    allow_seconds: bool = True,
    by_meal: bool = True,
) -> Dict[str, Any]:
    """Choose meals for each day so the day meets its targets.

    Works down the day one sitting at a time, each time taking whichever recipe
    best closes what is still missing within the calories left. A recipe can
    appear more than once -- meal prep is repetitive on purpose -- but not more
    than `max_repeats` times across the week, so the plan is not one dish
    seven days running.

    With `by_meal` the sittings are named: breakfast, then lunch, then dinner,
    and only recipes belonging to that sitting are considered. Without it the
    numbers still work out and the day suggests chicken ragu for breakfast,
    which is a plan nobody follows.
    """
    if not library:
        return {"days": [], "message": "There are no recipes to plan with."}

    usable = [r for r in library if (r.get("perServing") or {}).get("kcal")]
    if not usable:
        return {"days": [], "message": "Saved recipes have no nutrition figures."}

    used_count: Dict[int, int] = {}
    out_days: List[Dict[str, Any]] = []
    sittings = _sittings(meals_per_day) if by_meal else [None] * meals_per_day

    for _ in range(days):
        total = {"kcal": 0.0, "p": 0.0, "c": 0.0, "f": 0.0, "fb": 0.0}
        chosen: List[Dict[str, Any]] = []

        for slot, sitting in enumerate(sittings):
            gap = _shortfall(total, goals)
            slots_left = meals_per_day - slot
            # Leave room for the meals still to come, so the first two do not
            # eat the whole day's calories.
            budget = gap["kcal"] / slots_left if slots_left else gap["kcal"]

            best = None
            best_score = 0.0
            for recipe in usable:
                if not recipe_suits(recipe, sitting):
                    continue
                if used_count.get(recipe["id"], 0) >= max_repeats:
                    continue
                if any(c["recipeId"] == recipe["id"] for c in chosen):
                    continue        # not the same dish twice in one day
                m = _macros(recipe)
                # A meal may overshoot its share, but not the day's ceiling.
                if m["kcal"] > gap["kcal"]:
                    continue
                score = _fit_score(m, gap)
                # Prefer meals near the slot's budget; a tiny one wastes a slot.
                if budget > 0:
                    score *= 1.0 - min(0.6, abs(m["kcal"] - budget) / (budget * 3))
                # Something already eaten this week is worth less than
                # something new. Without this the greedy pick is deterministic
                # and every day comes out identical, which is a menu nobody
                # would accept even when the numbers are right.
                seen = used_count.get(recipe["id"], 0)
                score *= 1.0 / (1.0 + seen * 0.9)
                if score > best_score:
                    best, best_score = recipe, score

            if best is None:
                # Nothing fits this sitting -- usually the library has no
                # breakfast. Skip it rather than abandon the rest of the day.
                continue

            m = _macros(best)
            for k in total:
                total[k] += m[k]
            used_count[best["id"]] = used_count.get(best["id"], 0) + 1
            chosen.append({"recipeId": best["id"], "servings": 1, "on": True,
                           "meal": sitting or "", "name": best.get("name", "")})

        # A day still short on protein with calories to spare gets a second
        # helping of whatever on it carries the most protein per calorie.
        if allow_seconds and chosen:
            gap = _shortfall(total, goals)
            guard = 0
            while gap["p"] > 0 and gap["kcal"] > 0 and guard < 4:
                guard += 1
                pick = None
                pick_ratio = 0.0
                for c in chosen:
                    r = next((x for x in usable if x["id"] == c["recipeId"]), None)
                    if not r:
                        continue
                    m = _macros(r)
                    if m["kcal"] > gap["kcal"] or m["kcal"] <= 0:
                        continue
                    ratio = m["p"] / m["kcal"]
                    if ratio > pick_ratio:
                        pick, pick_ratio = c, ratio
                if pick is None:
                    break
                pick["servings"] += 1
                r = next(x for x in usable if x["id"] == pick["recipeId"])
                m = _macros(r)
                for k in total:
                    total[k] += m[k]
                gap = _shortfall(total, goals)

        met = {
            "kcal": total["kcal"] <= goals["ceiling"],
            "protein": total["p"] >= goals["floorP"],
            "fibre": total["fb"] >= goals["floorF"],
        }
        out_days.append({
            "meals": [{k: v for k, v in c.items() if k != "name"} for c in chosen],
            "names": [c["name"] for c in chosen],
            "totals": {k: round(v, 1) for k, v in total.items()},
            "met": met,
            "allMet": all(met.values()),
        })

    good = sum(1 for d in out_days if d["allMet"])
    return {
        "days": out_days,
        "daysMeetingTargets": good,
        "message": _summarise(out_days, goals),
    }


def _summarise(days: List[Dict[str, Any]], goals: Dict[str, float]) -> str:
    good = sum(1 for d in days if d["allMet"])
    if not days:
        return "Nothing could be planned."
    if good == len(days):
        return f"All {len(days)} days meet every target."

    missing = []
    if any(not d["met"]["protein"] for d in days):
        worst = min(d["totals"]["p"] for d in days)
        missing.append(f"protein (lowest day {worst:.0f}g of {goals['floorP']:.0f}g)")
    if any(not d["met"]["fibre"] for d in days):
        worst = min(d["totals"]["fb"] for d in days)
        missing.append(f"fibre (lowest day {worst:.0f}g of {goals['floorF']:.0f}g)")
    if any(not d["met"]["kcal"] for d in days):
        missing.append("the calorie ceiling")

    return (f"{good} of {len(days)} days meet every target. "
            f"Short on {', and '.join(missing)}. "
            f"More high-protein or high-fibre recipes in the library would fix it.")


def rebalance(
    ingredients: Sequence[Dict[str, Any]],
    changed_food: str,
    new_grams: float,
    target_key: str = "p",
) -> Dict[str, Any]:
    """After changing one ingredient, how much more of each other restores it.

    Reports one option per remaining ingredient rather than silently picking,
    because which to increase is a matter of taste, cost and what is in the
    cupboard -- none of which this can know.
    """
    lookup = recipe_lib.INGREDIENTS

    def _grams(item: Dict[str, Any]) -> Optional[float]:
        """A recipe calls it gramsPerServing; a bare list calls it grams.

        Reading only one of them meant handing a recipe's own ingredients
        straight back produced a KeyError and a 500, which is the most obvious
        thing anyone would try.
        """
        for key in ("grams", "gramsPerServing", "gramsTotal"):
            value = item.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    known = [{**i, "grams": _grams(i)} for i in ingredients
             if i.get("food") in lookup and _grams(i) is not None]
    if not known:
        return {"status": "error",
                "message": "None of those ingredients had a weight to work from."}
    changed = next((i for i in known if i["food"] == changed_food), None)
    if changed is None:
        return {"status": "error",
                "message": "That ingredient is not one with known nutrition."}

    def totals(items, override=None):
        out = {"kcal": 0.0, "p": 0.0, "c": 0.0, "f": 0.0, "fb": 0.0}
        for item in items:
            grams = override if (override is not None
                                 and item["food"] == changed_food) else item["grams"]
            meta = lookup[item["food"]]
            for k in out:
                out[k] += meta[k] * grams / 100.0
        return out

    before = totals(known)
    after = totals(known, new_grams)
    delta = {k: round(after[k] - before[k], 1) for k in before}

    shortfall = before[target_key] - after[target_key]
    options = []
    for item in known:
        if item["food"] == changed_food:
            continue
        meta = lookup[item["food"]]
        per_gram = meta[target_key] / 100.0
        if per_gram <= 0:
            continue
        extra = shortfall / per_gram
        options.append({
            "food": item["food"],
            "currentGrams": item["grams"],
            "changeGrams": round(extra),
            "newGrams": max(0, round(item["grams"] + extra)),
            "costsKcal": round(meta["kcal"] * extra / 100.0),
            "alsoAddsFibre": round(meta["fb"] * extra / 100.0, 1),
        })

    # Whatever restores the target for the fewest extra calories comes first.
    options.sort(key=lambda o: abs(o["costsKcal"]))

    return {
        "status": "ok",
        "changed": changed_food,
        "fromGrams": changed["grams"],
        "toGrams": new_grams,
        "delta": delta,
        "target": target_key,
        "shortfall": round(shortfall, 1),
        "options": options[:5],
    }
