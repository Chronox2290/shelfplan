"""Import a recipe from a page the user points at.

Deliberately an importer, not a search engine. Recipe *ingredient lists* are
largely facts, but the method prose is the author's copyrighted writing, and
crawling the big cooking sites to build a searchable store of condensed copies
would be redistributing their work. Every serious recipe manager -- Paprika,
Mealie, Tandoor -- works the way this does instead: the person supplies a link
to a page they are already reading, the recipe is saved for their own use, and
the source is credited and linked.

The extraction uses schema.org/Recipe JSON-LD, which sites publish on purpose
for machines to read, so nothing here depends on scraping page markup.
"""

from typing import Any, Dict, List, Optional, Tuple
import html as html_lib
import json
import re

import requests

from . import safefetch

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}

_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)

# ---------------------------------------------------------------- units ----

# Everything is normalised to millilitres or grams, then presented in whichever
# system was asked for.
_VOLUME_ML = {
    "cup": 250.0, "cups": 250.0, "c": 250.0,          # metric cup
    "tablespoon": 20.0, "tablespoons": 20.0, "tbsp": 20.0, "tbs": 20.0,
    "teaspoon": 5.0, "teaspoons": 5.0, "tsp": 5.0,
    "millilitre": 1.0, "millilitres": 1.0, "ml": 1.0,
    "litre": 1000.0, "litres": 1000.0, "l": 1000.0, "liter": 1000.0,
    "fluid ounce": 29.57, "fl oz": 29.57, "floz": 29.57,
    "pint": 568.0, "pints": 568.0, "quart": 946.0,
}

_WEIGHT_G = {
    "gram": 1.0, "grams": 1.0, "g": 1.0, "gr": 1.0,
    "kilogram": 1000.0, "kilograms": 1000.0, "kg": 1000.0,
    "ounce": 28.35, "ounces": 28.35, "oz": 28.35,
    "pound": 453.6, "pounds": 453.6, "lb": 453.6, "lbs": 453.6,
}

# A cup of flour and a cup of honey are not the same weight. Only the common
# ones are listed; anything else stays a volume rather than being guessed at.
_DENSITY_G_PER_ML = {
    "flour": 0.53, "sugar": 0.85, "brown sugar": 0.90, "icing sugar": 0.56,
    "rice": 0.80, "oats": 0.40, "butter": 0.91, "honey": 1.42,
    "milk": 1.03, "water": 1.00, "oil": 0.92, "yoghurt": 1.03,
    "breadcrumbs": 0.35, "cocoa": 0.41, "salt": 1.20,
}

# "1 1/2", "1½", "1.5", "1-2"
_FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
              "⅕": 0.2, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}

_QTY = re.compile(
    r"^\s*(\d+\s*\d*/\d+|\d+[.,]?\d*\s*[-–to]{1,2}\s*\d+[.,]?\d*|\d+[.,]?\d*|["
    + "".join(_FRACTIONS) + r"])\s*")


def _parse_quantity(text: str) -> Tuple[Optional[float], str]:
    """Leading amount and whatever follows it."""
    for symbol, value in _FRACTIONS.items():
        if text.strip().startswith(symbol):
            return value, text.strip()[len(symbol):].strip()

    match = _QTY.match(text)
    if not match:
        return None, text.strip()
    raw = match.group(1).strip()
    rest = text[match.end():].strip()

    # A range ("1-2 onions") becomes its midpoint.
    range_match = re.match(r"^(\d+[.,]?\d*)\s*[-–to]{1,2}\s*(\d+[.,]?\d*)$", raw)
    if range_match:
        low = float(range_match.group(1).replace(",", "."))
        high = float(range_match.group(2).replace(",", "."))
        return (low + high) / 2, rest

    mixed = re.match(r"^(\d+)\s+(\d+)/(\d+)$", raw)
    if mixed:
        return (int(mixed.group(1))
                + int(mixed.group(2)) / int(mixed.group(3))), rest

    simple = re.match(r"^(\d+)/(\d+)$", raw)
    if simple:
        return int(simple.group(1)) / int(simple.group(2)), rest

    try:
        return float(raw.replace(",", ".")), rest
    except ValueError:
        return None, text.strip()


def parse_ingredient(line: str) -> Dict[str, Any]:
    """Split "2 cups plain flour, sifted" into its parts.

    Keeps the original text whatever happens, so a line this cannot read is
    still shown to the cook exactly as the author wrote it.
    """
    original = " ".join((line or "").split())
    # Some sites append their own costings to each line -- "cumin ($0.05)".
    # That is their bookkeeping, not part of the ingredient.
    original = re.sub(r"\s*\(\s*\$[\d.,]+\s*\)\s*$", "", original).strip()
    qty, rest = _parse_quantity(original)

    unit = None
    grams = None
    millilitres = None

    if qty is not None:
        # Longest unit names first, so "fluid ounce" wins over "ounce".
        for name in sorted(list(_VOLUME_ML) + list(_WEIGHT_G),
                           key=len, reverse=True):
            pattern = r"^" + re.escape(name) + r"\b\.?\s*"
            if re.match(pattern, rest, re.I):
                unit = name
                rest = re.sub(pattern, "", rest, flags=re.I).strip()
                break

    item = re.sub(r"^(of|de)\s+", "", rest, flags=re.I).strip()

    if unit and qty is not None:
        if unit in _WEIGHT_G:
            grams = qty * _WEIGHT_G[unit]
        else:
            millilitres = qty * _VOLUME_ML[unit]
            lowered = item.lower()
            for key, density in _DENSITY_G_PER_ML.items():
                if key in lowered:
                    grams = millilitres * density
                    break

    return {
        "original": original,
        "quantity": qty,
        "unit": unit,
        "item": item or original,
        "grams": round(grams, 1) if grams else None,
        "millilitres": round(millilitres, 1) if millilitres else None,
    }


def _round_nicely(value: float):
    """A cook-friendly number. Whole values lose the decimal point.

    "4.0 chicken breasts" is how a machine writes it; "4 chicken breasts" is
    how a recipe does.
    """
    if value >= 100:
        out = round(value / 5) * 5
    elif value >= 20:
        out = round(value)
    elif value >= 1:
        out = round(value * 2) / 2
    else:
        out = round(value, 2)
    return int(out) if float(out).is_integer() else out


# Spoons and cups are how recipes are written in both systems, so they stay
# spoons and cups. Turning "1 1/2 tsp salt" into "9 g salt" is technically a
# conversion and practically useless: nobody weighs salt.
#
# They are not the same size in both systems, though, and the tablespoon is not
# close: an Australian one is 20ml and holds four teaspoons, an American one is
# 15ml and holds three. Ignoring that leaves the metric/imperial switch doing
# visibly nothing on a recipe written entirely in cups and spoons -- and quietly
# wrong by a quarter on anything raised with bicarbonate.
_COOKS_UNITS = {
    "cup", "cups", "c", "tablespoon", "tablespoons", "tbsp", "tbs",
    "teaspoon", "teaspoons", "tsp", "pinch", "pinches", "handful",
}

# Millilitres per unit, by system. Quantities are parsed as Australian, which
# is what this app is for and what _VOLUME_ML already assumes.
_COOKS_ML = {
    "metric": {"cups": 250.0, "tbsp": 20.0, "tsp": 5.0},
    "imperial": {"cups": 240.0, "tbsp": 15.0, "tsp": 5.0},
}


def _in_system(unit: str, qty: float, system: str) -> float:
    """The same amount, counted in that system's version of the unit."""
    here = _COOKS_ML.get(system) or _COOKS_ML["metric"]
    mine = _COOKS_ML["metric"].get(unit)
    theirs = here.get(unit)
    if not mine or not theirs:
        return qty
    return qty * mine / theirs

# Units a cook says out loud, in the singular, keyed by what recipes write.
_UNIT_LABEL = {
    "c": "cups", "tbs": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp",
}


def present(part: Dict[str, Any], system: str = "metric",
            scale: float = 1.0) -> str:
    """One ingredient line, scaled, in the measure the recipe used.

    The old rule was "if we can work out the grams, say grams", which turned
    "2 cups buttermilk" into "455 g buttermilk" and "1 1/2 tsp baking soda"
    into nothing at all. Both are worse than what the recipe said, and the
    gram figure is our own conversion rather than the writer's -- a cup of
    flour is 265g by the table here and 300g by some recipes, so the number
    quietly disagreed with the page it came from.

    So: keep the kind of measure the line was written in, and scale it. Grams
    and millilitres are still worked out, and are offered alongside by
    `equivalent()` for shopping, where they genuinely help.
    """
    qty = part.get("quantity")
    if qty is None:
        return part["original"]

    item = part["item"]
    unit = (part.get("unit") or "").lower()

    # Cups and spoons: the same words in both systems. Scale, do not convert.
    if unit in _COOKS_UNITS:
        label = _UNIT_LABEL.get(unit, unit)
        scaled_qty = _in_system(label, qty * scale, system)
        amount = _round_spoons(scaled_qty)
        return f"{amount} {_plural(label, scaled_qty)} {item}".strip()

    grams = part.get("grams")
    millilitres = part.get("millilitres")
    by_weight = unit in _WEIGHT_G

    if system == "imperial":
        if by_weight and grams:
            value = grams * scale
            if value >= 453.6:
                return f"{_round_nicely(value / 453.6)} lb {item}"
            return f"{_round_nicely(value / 28.35)} oz {item}"
        if millilitres:
            value = millilitres * scale
            if value >= 236:
                return f"{_round_nicely(value / 236.6)} cups {item}"
            if value >= 29:
                return f"{_round_nicely(value / 29.57)} fl oz {item}"
            return f"{_round_nicely(value / 14.79)} tbsp {item}"
        if grams:
            value = grams * scale
            if value >= 453.6:
                return f"{_round_nicely(value / 453.6)} lb {item}"
            return f"{_round_nicely(value / 28.35)} oz {item}"
    else:
        if by_weight and grams:
            value = grams * scale
            if value >= 1000:
                return f"{_round_nicely(value / 1000)} kg {item}"
            return f"{_round_nicely(value)} g {item}"
        if millilitres:
            value = millilitres * scale
            if value >= 1000:
                return f"{_round_nicely(value / 1000)} L {item}"
            return f"{_round_nicely(value)} ml {item}"
        if grams:
            value = grams * scale
            if value >= 1000:
                return f"{_round_nicely(value / 1000)} kg {item}"
            return f"{_round_nicely(value)} g {item}"

    # No unit at all: "2 eggs", "1 lemon".
    scaled = _round_nicely(qty * scale)
    suffix = f" {part['unit']}" if part.get("unit") else ""
    return f"{scaled}{suffix} {item}".strip()


def equivalent(part: Dict[str, Any], scale: float = 1.0,
               system: str = "metric") -> str:
    """What that line weighs or measures, where it is worth saying.

    Useful for a shopping list and for a cook with scales, and pointless
    alongside a line that already gives grams. Marked as an approximation
    because it is one -- these come from a density table, not from the recipe.

    It follows the system asked for, which is most of what switching to
    imperial is *for*: a cup is a cup in both, so if this stayed in grams the
    switch looked like it did nothing at all.
    """
    unit = (part.get("unit") or "").lower()
    if unit not in _COOKS_UNITS:
        return ""            # the line already says grams or millilitres
    item = (part.get("item") or "").lower()
    millilitres = part.get("millilitres")
    grams = part.get("grams")
    # A cup of flour is worth knowing in grams; a cup of buttermilk is worth
    # knowing in millilitres. Weighing a liquid is nobody's idea of a help.
    liquid = any(word in item for word in _LIQUIDS)
    if liquid and millilitres and millilitres * scale >= 15:
        return "about " + _volume(millilitres * scale, system)
    if grams and grams * scale >= 10:
        return "about " + _weight(grams * scale, system)
    if millilitres and millilitres * scale >= 15:
        return "about " + _volume(millilitres * scale, system)
    return ""


def _weight(grams: float, system: str) -> str:
    if system == "imperial":
        if grams >= 453.6:
            return f"{_round_spoons(grams / 453.6)} lb"
        return f"{_round_spoons(grams / 28.35)} oz"
    if grams >= 1000:
        return f"{_round_nicely(grams / 1000)} kg"
    return f"{_round_nicely(grams)} g"


def _volume(millilitres: float, system: str) -> str:
    if system == "imperial":
        if millilitres >= 473:
            pints = millilitres / 473.2
            return (f"{_round_spoons(pints)} US "
                    f"{'pint' if pints <= 1.0 else 'pints'}")
        return f"{_round_spoons(millilitres / 29.57)} fl oz"
    if millilitres >= 1000:
        return f"{_round_nicely(millilitres / 1000)} L"
    return f"{_round_nicely(millilitres)} ml"


# How a measuring cup is actually marked, and how a recipe actually reads.
_EIGHTHS = {1: "1/8", 2: "1/4", 3: "3/8", 4: "1/2", 5: "5/8", 6: "3/4",
            7: "7/8"}


def _round_spoons(value: float) -> str:
    """A spoon or cup amount as a cook would write it.

    "1.75 cups" is a number a computer produced. A recipe says 1 3/4, and a
    measuring cup has the line for it.
    """
    if value >= 10:
        return str(_round_nicely(value))
    if value <= 0:
        return "a pinch of"
    whole = int(value)
    rest = value - whole
    # Thirds are marked on cups and spoons and are not eighths, so they are
    # checked before the eighths that would otherwise swallow them.
    if abs(rest - 1 / 3) < 0.04:
        fraction = "1/3"
    elif abs(rest - 2 / 3) < 0.04:
        fraction = "2/3"
    else:
        eighths = round(rest * 8)
        if eighths == 8:
            whole, eighths = whole + 1, 0
        fraction = _EIGHTHS.get(eighths, "")
    if not fraction:
        return str(whole) if whole else "a pinch of"
    return f"{whole} {fraction}" if whole else fraction


def _plural(unit: str, value: float) -> str:
    """"1 cup" and "3/4 cup", not "1 cups"."""
    return "cup" if (unit == "cups" and value <= 1.0) else unit


# Things measured in cups whose useful equivalent is a volume, not a weight.
_LIQUIDS = (
    "milk", "buttermilk", "water", "oil", "juice", "cream", "stock", "broth",
    "wine", "vinegar", "yoghurt", "yogurt", "sauce", "passata", "puree",
)


# ------------------------------------------------------------ extraction ---

def _walk(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from _walk(value)


def _is_recipe(node: Dict[str, Any]) -> bool:
    kind = node.get("@type")
    if isinstance(kind, list):
        return any(str(k).lower() == "recipe" for k in kind)
    return str(kind).lower() == "recipe"


def _text(value: Any) -> str:
    if isinstance(value, str):
        # Titles routinely arrive as "Pizza &amp; Dough" straight from the page.
        return " ".join(html_lib.unescape(value).split())
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or "")
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return ""


def _steps(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        parts = re.split(r"(?:\r?\n)+|(?<=[.!?])\s{2,}", value)
        return [" ".join(p.split()) for p in parts if p.strip()]
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and entry.get("@type") == "HowToSection":
                out.extend(_steps(entry.get("itemListElement")))
            else:
                text = _text(entry)
                if text:
                    out.append(text)
    return out


def _servings(value: Any) -> Optional[int]:
    text = _text(value)
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def _duration(value: Any) -> Tuple[str, Optional[int]]:
    """ISO 8601 duration to (something readable, total minutes).

    The minutes are what a Sunday cook sheet can actually schedule against;
    the display string is what a person reads. Both come from the same parse
    so they cannot disagree with each other.
    """
    text = _text(value)
    match = re.match(r"^P(?:T)?(?:(\d+)H)?(?:(\d+)M)?", text)
    if not match or not (match.group(1) or match.group(2)):
        return text, None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    if hours and minutes:
        return f"{hours}h {minutes}m", total
    if hours:
        return f"{hours}h", total
    return f"{minutes} min", total


def extract(html: str, url: str = "") -> Optional[Dict[str, Any]]:
    """Pull a recipe out of a page's JSON-LD, or None if there is not one."""
    for block in _JSONLD.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            # Some sites emit several objects back to back.
            try:
                data = json.loads("[" + block.replace("}\n{", "},{") + "]")
            except ValueError:
                continue
        for node in _walk(data):
            if not _is_recipe(node):
                continue
            raw_ingredients = node.get("recipeIngredient") or node.get("ingredients") or []
            if isinstance(raw_ingredients, str):
                raw_ingredients = [raw_ingredients]
            parts = [parse_ingredient(_text(line)) for line in raw_ingredients]
            author = node.get("author")
            prep_text, prep_min = _duration(node.get("prepTime"))
            cook_text, cook_min = _duration(node.get("cookTime"))
            total_text, total_min = _duration(node.get("totalTime"))
            return {
                "name": _text(node.get("name")) or "Imported recipe",
                "author": _text(author.get("name") if isinstance(author, dict) else author),
                "servings": _servings(node.get("recipeYield")),
                "prepTime": prep_text,
                "cookTime": cook_text,
                "totalTime": total_text,
                # Minutes, for anything that schedules against them. None
                # where the page did not say -- a guess here would show up as
                # a confident number on a Sunday cook sheet.
                "prepMinutes": prep_min,
                "cookMinutes": cook_min,
                "totalMinutes": total_min,
                "cuisineText": _text(node.get("recipeCuisine")),
                "ingredients": parts,
                "steps": _steps(node.get("recipeInstructions")),
                "image": _first_image(node.get("image")),
                "sourceUrl": url,
                "sourceName": _host(url),
            }
    return None


def _first_image(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _first_image(value.get("url") or value.get("contentUrl"))
    if isinstance(value, list) and value:
        return _first_image(value[0])
    return ""


def _host(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "")
    return match.group(1).replace("www.", "") if match else ""


def fetch(url: str, timeout: int = 20) -> Dict[str, Any]:
    """Fetch one page and extract its recipe."""
    if not re.match(r"^https?://", url or ""):
        return {"status": "error", "message": "That does not look like a web address."}
    # Fetching whatever address a caller supplies is a way to reach the network
    # this server is sitting on, and this one is built to sit on a home NAS.
    # It would happily fetch 127.0.0.1 and the router's admin page otherwise.
    try:
        safefetch.check_url(url, schemes=("http", "https"))
    except safefetch.Refused as exc:
        return {"status": "error", "message": str(exc)}
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout,
                                allow_redirects=False)
        # A redirect is a second address, and the first check said nothing
        # about it.
        while response.is_redirect and response.headers.get("location"):
            nxt = requests.compat.urljoin(url, response.headers["location"])
            safefetch.check_url(nxt, schemes=("http", "https"))
            url = nxt
            response = requests.get(url, headers=_HEADERS, timeout=timeout,
                                    allow_redirects=False)
    except safefetch.Refused as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"Could not reach that page: {exc}"}
    if response.status_code != 200:
        return {"status": "error",
                "message": f"That page returned {response.status_code}."}

    recipe = extract(response.text, url)
    if recipe is None:
        return {"status": "error",
                "message": ("No recipe data on that page. It works with sites "
                            "that publish a structured recipe, which most large "
                            "cooking sites do -- try the printable version of "
                            "the page if there is one.")}
    return {"status": "success", "recipe": recipe}


def _scaled_grams(part: Dict[str, Any], scale: float) -> Optional[float]:
    """The true weight of one line at the current serving count, or None.

    Only when the weight is *known* -- from the unit itself, or from the
    density table for a handful of common cooking liquids and staples.
    Guessing from millilitres with no density (a cup of loosely-packed basil
    leaves has no honest gram figure) is exactly how the app's own nutrition
    and shopping figures went quietly wrong before, so this stays None rather
    than assume water.
    """
    grams = part.get("grams")
    return round(grams * scale, 1) if grams is not None else None


def scale_recipe(recipe: Dict[str, Any], servings: Optional[int] = None,
                 system: str = "metric") -> Dict[str, Any]:
    """Re-present a recipe at a different serving count and measuring system."""
    original = recipe.get("servings") or 0
    factor = (servings / original) if (servings and original) else 1.0
    return {
        **recipe,
        "servings": servings or original or None,
        "scale": round(factor, 3),
        "system": system,
        "lines": [present(part, system, factor)
                  for part in recipe.get("ingredients", [])],
        # What each line weighs, where the line is in cups or spoons and the
        # answer is worth having. Kept separate from the line itself so the
        # page can show it quietly rather than in place of the measure.
        "equivalents": [equivalent(part, factor, system)
                        for part in recipe.get("ingredients", [])],
        # What the page itself said, which is the authority when our own
        # conversion disagrees with it.
        "original": [part.get("original", "")
                     for part in recipe.get("ingredients", [])],
        # The number a nutrition estimate and a shopping line can actually use
        # -- at THIS serving count, not the one the page was written for.
        "scaledGrams": [_scaled_grams(part, factor)
                        for part in recipe.get("ingredients", [])],
    }
