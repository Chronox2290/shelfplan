"""Pick the right product for a planned food, and price it on the plan's basis.

Two things make a naive "take the first search hit" wrong for meal planning:

* Pack size. A 500g chicken thigh pack and a 1.5kg one are both correct hits,
  but they differ by ~30% per kilo. The plan already records the pack it buys,
  so the closest pack is the honest comparison.
* Drained weight. A food recorded as "drained" carries the drained mass, while
  the shelf pack is the gross tin. Comparing $/kg across those two bases
  reports a 40% price drop that never happened.
"""

from typing import Any, Dict, List, Optional
import re

from . import catalog
from . import coles_catalog

# Words that mean the plan's pack figure is drained/prepared mass rather than
# the gross pack the store sells.
_DRAINED = re.compile(r"\b(drained|cooked|prepared)\b", re.I)

_STOPWORDS = {
    "the", "and", "with", "of", "a", "each", "loose", "pack", "tin",
    "g", "kg", "ml", "l",
}

# Qualifier groups whose members are mutually exclusive. Wanting one member and
# being offered another is disqualifying, not merely a weaker match: brown rice
# is not white rice, and a wholemeal wrap is not a white one. Token overlap
# alone cannot see this, because it only ever rewards words that agree.
_CONFLICTS: List[set] = [
    {"brown", "white", "wholemeal", "wholegrain", "multigrain", "rye"},
    {"fresh", "frozen", "canned", "tinned", "dried"},
    {"skinless", "skin"},
    {"fillet", "mince", "diced", "steak", "tenderloin",
     "schnitzel", "crumbed", "nugget", "kiev"},
    {"breast", "thigh", "wing", "drumstick"},
    {"natural", "vanilla", "strawberry", "chocolate", "honey", "mango"},
    {"salted", "unsalted"},
    {"raw", "cooked", "roasted"},
    {"mini", "large", "jumbo"},
    {"springwater", "oil", "brine"},
]


def _singular(word: str) -> str:
    """Crude depluralisation, enough to stop 'fillets' clashing with 'fillet'."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set:
    return {
        _singular(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if w not in _STOPWORDS and not w.isdigit()
    }


# Words that mark a product as a *prepared form* of an ingredient rather than
# the ingredient. Asking for capsicum and being offered capsicum relish is not
# a near miss, it is a different item -- but the words overlap almost entirely,
# so pure token similarity cannot tell them apart and pack-size tie-breaking
# hands the win to the jar.
_FORM_WORDS = frozenset("""
relish chutney sauce paste pickle pickled dip juice powder seasoning
spice stock soup crisp chip jerky marinade dressing jam spread flavoured
flavour extract essence syrup cordial pesto salsa hummus dukkah rub
""".split())


def form_penalty(wanted: str, candidate: str) -> float:
    """Candidate is a prepared form of something the request wanted plain."""
    want = _tokens(wanted)
    have = _tokens(candidate)
    if want & _FORM_WORDS:
        return 0.0            # a relish was actually asked for
    return 1.0 if (have & _FORM_WORDS) else 0.0


def conflict_penalty(wanted: str, candidate: str) -> float:
    """How strongly the candidate contradicts the wanted food.

    Returns the count of qualifier groups where the two names pick different
    members -- e.g. wanting "brown" and being offered "white".
    """
    a, b = _tokens(wanted), _tokens(candidate)
    clashes = 0
    for group in _CONFLICTS:
        want = a & group
        have = b & group
        if want and have and not (want & have):
            clashes += 1
    return float(clashes)


def name_similarity(wanted: str, candidate: str) -> float:
    """How well a candidate name matches, both ways round.

    Counting only how many wanted words appear (recall) makes "Broccoli" and
    "Frozen Carrot Cauliflower & Broccoli" score identically, because extra
    words cost nothing -- and then pack size decides, which is how a bag of
    mixed vegetables wins a search for broccoli. Words in the candidate that
    were not asked for have to count against it, so this is the harmonic mean
    of both directions: everything asked for is present, and little else is.
    """
    a, b = _tokens(wanted), _tokens(candidate)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if not overlap:
        return 0.0
    recall = overlap / len(a)
    precision = overlap / len(b)
    return 2 * recall * precision / (recall + precision)


def pack_closeness(target_g: Optional[float], pack_g: Optional[float]) -> float:
    """1.0 for an exact pack match, decaying with the ratio between them."""
    if not target_g or not pack_g:
        return 0.0
    ratio = max(target_g, pack_g) / min(target_g, pack_g)
    return 1.0 / ratio


def score(product: Dict[str, Any], wanted: str, target_g: Optional[float]) -> float:
    """Rank a candidate: right product first, then right pack, then buyable.

    Pack size only breaks ties between products that are already plausibly the
    same thing. Letting it compete with identity is what promotes a 360g pack
    of white wraps over a 500g pack of the wholemeal ones actually wanted.
    """
    name = product.get("name", "")
    similarity = name_similarity(wanted, name)

    # A contradicted qualifier sinks the candidate outright, and so does being
    # a jar of something when the recipe wanted the vegetable.
    s = (3.0 * similarity
         - 2.5 * conflict_penalty(wanted, name)
         - 3.0 * form_penalty(wanted, name))

    # Pack closeness is a tie-breaker, and only once identity is credible.
    if similarity >= 0.5:
        s += 1.0 * pack_closeness(target_g, product.get("pack_g"))

    if product.get("in_stock"):
        s += 0.15
    if product.get("per_kg") is not None:
        s += 0.15
    return s


def rank_key(
    product: Dict[str, Any], wanted: str, target_g: Optional[float]
) -> tuple:
    """Identity first; where identity genuinely ties, the better buy wins.

    "Polenta" describes "La Gina Polenta Corn Meal 500g" and "Marco Polo
    Polenta 750g" exactly as well -- both are polenta, and everything else in
    either name is brand and packaging. Nothing in the words can separate them,
    so the order the store happened to list them in was deciding, which is how
    a search for polenta settles on the dearer corn meal.

    This is a price tool. When two candidates are equally the right thing, the
    cheaper kilo is the answer. Scores are compared rounded, because a
    hundredth of a point is noise rather than a real preference, and a
    candidate with no weight basis sorts last so it can never win on a price
    per kilo it does not have.
    """
    per_kg = product.get("per_kg")
    value = -per_kg if per_kg else float("-inf")
    return (round(score(product, wanted, target_g), 2), value)


_SEARCHERS = {
    "woolworths": lambda q, limit: catalog.search(q, limit=limit),
    "coles": lambda q, limit: coles_catalog.search(q, limit=limit),
}


def resolve_food(
    food: str,
    query: str,
    target_pack_g: Optional[float] = None,
    drained: Optional[bool] = None,
    limit: int = 12,
    store: str = "woolworths",
) -> Dict[str, Any]:
    """Look a planned food up and return a price record on the plan's basis.

    `target_pack_g` is the pack the plan already buys; the closest match wins.
    When the food is recorded drained, the returned `pack` stays the drained
    mass so the plan's own $/kg arithmetic keeps meaning the same thing.
    """
    if drained is None:
        drained = bool(_DRAINED.search(food))

    searcher = _SEARCHERS.get(store)
    if searcher is None:
        return {"food": food, "query": query, "status": "error",
                "message": f"Unknown store {store!r}.", "store": store}

    found = searcher(query, limit)
    if found["status"] != "success" or not found["products"]:
        return {
            "food": food,
            "query": query,
            "status": "not_found",
            "store": store,
            "message": found.get("message", "no products returned"),
        }
    return resolve_from_products(
        food, query, found["products"], target_pack_g, drained)


def resolve_from_products(
    food: str,
    query: str,
    products: List[Dict[str, Any]],
    target_pack_g: Optional[float] = None,
    drained: Optional[bool] = None,
) -> Dict[str, Any]:
    """Rank an existing candidate list -- no network access.

    Kept separate from resolve_food so cached results can be scored without
    another request to the store.
    """
    if drained is None:
        drained = bool(_DRAINED.search(food))
    if not products:
        return {"food": food, "query": query, "status": "not_found",
                "message": "no products supplied"}
    found = {"products": products}

    # Both strings describe the same target: the curated store name carries the
    # brand and pack, the plan's food name carries qualifiers like "drained".
    wanted = f"{query} {food}"
    ranked = sorted(
        found["products"],
        key=lambda p: rank_key(p, wanted, target_pack_g),
        reverse=True,
    )
    best = ranked[0]

    gross_g = best.get("pack_g")
    per_kg = best.get("per_kg")
    pack_price = best.get("pack_price")

    # Keep the plan's basis. The pack price is what the shelf charges either
    # way; only the mass it is divided by changes.
    if drained and target_pack_g and gross_g:
        basis_g = target_pack_g
        basis = "drained"
    elif gross_g:
        basis_g = gross_g
        basis = "gross"
    else:
        basis_g = target_pack_g
        basis = "assumed"

    effective_per_kg = (
        round(pack_price * 1000.0 / basis_g, 2)
        if pack_price is not None and basis_g
        else per_kg
    )

    # Say how much to trust this, rather than letting a bad match overwrite a
    # good hand-checked figure silently.
    similarity = name_similarity(wanted, best.get("name", ""))
    clashes = conflict_penalty(wanted, best.get("name", ""))
    reasons = []
    if form_penalty(wanted, best.get("name", "")):
        reasons.append("looks like a prepared version rather than the "
                       "ingredient itself")
    if clashes:
        reasons.append("contradicts a qualifier in the planned food")
    if similarity < 0.4:
        reasons.append("weak name match")
    if per_kg is None:
        reasons.append("sold per-each, no weight basis")
    if target_pack_g and gross_g:
        ratio = max(target_pack_g, gross_g) / min(target_pack_g, gross_g)
        if basis == "gross" and ratio > 1.6:
            reasons.append("pack size differs sharply from the planned pack")

    return {
        "food": food,
        "query": query,
        "status": "ok",
        "confidence": round(max(0.0, similarity - 0.5 * clashes), 2),
        "needs_review": bool(reasons),
        "review_reasons": reasons,
        "price": pack_price,
        "pack": round(basis_g) if basis_g else None,
        "per_kg": effective_per_kg,
        "basis": basis,
        "gross_pack_g": gross_g,
        "sold_per_each": per_kg is None,
        "matched_name": best.get("name"),
        "stockcode": best.get("stockcode"),
        "on_special": best.get("on_special"),
        "in_stock": best.get("in_stock"),
        "package_size": best.get("package_size"),
        "cup_string": best.get("cup_string"),
        "url": best.get("url"),
        "image": best.get("image", ""),
        "store": best.get("store") or store,
        "alternatives": [
            {
                "name": p.get("name"),
                "pack_g": p.get("pack_g"),
                "per_kg": p.get("per_kg"),
                "pack_price": p.get("pack_price"),
            }
            for p in ranked[1:4]
        ],
    }
