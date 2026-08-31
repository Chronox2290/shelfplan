"""Compose meal-prep recipes and cost them from live supermarket prices.

Recipes are built rather than retrieved: a template picks one ingredient from
each role, then the quantities are scaled to hit the requested protein and
calorie targets. That keeps the output honest -- every recipe carries the
macros it was solved for, and every gram maps to a shopping-list line that can
be priced.

Nutrition figures are per 100g of the raw ingredient and are approximate; they
are for planning, not for clinical use.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple
import hashlib

# name -> per-100g macros, shopping query, role, and dietary tags.
#   kcal, p (protein g), c (carb g), f (fat g), fb (fibre g)
INGREDIENTS: Dict[str, Dict[str, Any]] = {
    # --- proteins -------------------------------------------------------
    "Chicken breast, raw": dict(kcal=165, p=31.0, c=0.0, f=3.6, fb=0.0,
                                role="protein", query="RSPCA Chicken Breast Fillets",
                                pack=1000, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("traybake stirfry ragu curry bowl soup".split())),
    "Chicken thigh fillet, raw, skinless": dict(kcal=209, p=26.0, c=0.0, f=10.9, fb=0.0,
                                role="protein", query="Chicken Thigh Fillets Skinless",
                                pack=1000, tags={"meat"}, cook="oven", aisle="meat", suits=frozenset("traybake stirfry curry ragu bowl soup".split())),
    "Beef mince, lean, raw": dict(kcal=176, p=26.0, c=0.0, f=8.0, fb=0.0,
                                role="protein", query="Beef Mince Lean",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("ragu soup".split())),
    "Pork loin, raw": dict(kcal=143, p=26.0, c=0.0, f=3.5, fb=0.0,
                                role="protein", query="Pork Loin Steaks",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("stirfry traybake bowl".split())),
    "Salmon fillet, raw": dict(kcal=208, p=20.0, c=0.0, f=13.0, fb=0.0,
                                role="protein", query="Salmon Fillets Skin On",
                                pack=500, tags={"fish", "pescatarian"}, cook="oven", aisle="meat", suits=frozenset("traybake bowl".split())),
    "Tuna steak, raw": dict(kcal=132, p=28.0, c=0.0, f=1.3, fb=0.0,
                                role="protein", query="Yellowfin Tuna Steaks",
                                pack=1000, tags={"fish", "pescatarian"}, cook="pan", aisle="meat", suits=frozenset("stirfry bowl".split())),
    "Firm tofu": dict(kcal=144, p=15.0, c=2.8, f=8.7, fb=0.9,
                                role="protein", query="Firm Tofu",
                                pack=400, tags={"vegetarian", "vegan"}, cook="pan", aisle="fridge", suits=frozenset("stirfry curry bowl".split())),
    "Red kidney beans, drained": dict(kcal=127, p=8.7, c=15.0, f=0.5, fb=6.4,
                                role="protein", query="Red Kidney Beans 420g tin",
                                pack=250, tags={"vegetarian", "vegan"}, cook="simmer", aisle="pantry", suits=frozenset("ragu soup curry".split())),
    "Chickpeas, drained": dict(kcal=139, p=7.4, c=17.0, f=2.6, fb=6.0,
                                role="protein", query="Chickpeas 400g tin",
                                pack=240, tags={"vegetarian", "vegan"}, cook="simmer", aisle="pantry", suits=frozenset("curry soup traybake bowl".split())),
    "Eggs": dict(kcal=143, p=12.6, c=0.7, f=9.5, fb=0.0,
                                role="protein", query="Free Range Eggs 12 pack",
                                pack=700, tags={"vegetarian"}, cook="pan", aisle="fridge", suits=frozenset("bowl stirfry".split())),

    # --- bases ----------------------------------------------------------
    "Brown rice, dry": dict(kcal=362, p=7.5, c=76.0, f=2.7, fb=3.4,
                                role="base", query="Brown Medium Grain Rice 1kg",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="pantry", suits=frozenset("stirfry curry bowl".split())),
    "White basmati rice, dry": dict(kcal=356, p=8.1, c=78.0, f=0.9, fb=1.3,
                                role="base", query="Basmati Rice 1kg",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="pantry", suits=frozenset("stirfry curry bowl".split())),
    "Wholemeal pasta, dry": dict(kcal=348, p=13.0, c=67.0, f=2.5, fb=8.0,
                                role="base", query="Wholemeal Penne Pasta 500g",
                                pack=500, tags={"vegan"}, aisle="pantry", suits=frozenset("ragu soup bowl".split())),
    "Rolled oats": dict(kcal=379, p=13.0, c=68.0, f=6.5, fb=10.0,
                                role="base", query="Rolled Oats 1kg",
                                pack=1000, tags={"vegan"}, aisle="pantry", suits=frozenset("".split())),
    "Sweet potato, raw": dict(kcal=86, p=1.6, c=20.0, f=0.1, fb=3.0,
                                role="base", query="Gold Sweet Potato",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("traybake bowl curry soup".split())),
    "Potato, raw": dict(kcal=77, p=2.0, c=17.0, f=0.1, fb=2.2,
                                role="base", query="Brushed Potatoes 2kg",
                                pack=2000, tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("traybake soup".split())),
    "Couscous, dry": dict(kcal=376, p=12.8, c=77.0, f=0.6, fb=5.0,
                                role="base", query="Couscous 500g",
                                pack=500, tags={"vegan"}, aisle="pantry", suits=frozenset("bowl traybake".split())),

    # --- vegetables -----------------------------------------------------
    "Broccoli, raw": dict(kcal=34, p=2.8, c=7.0, f=0.4, fb=2.6,
                                role="veg", query="Broccoli", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Capsicum, raw": dict(kcal=31, p=1.0, c=6.0, f=0.3, fb=2.1,
                                role="veg", query="Red Capsicum", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Zucchini, raw": dict(kcal=17, p=1.2, c=3.1, f=0.3, fb=1.0,
                                role="veg", query="Green Zucchini", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Green beans, frozen": dict(kcal=31, p=1.8, c=7.0, f=0.1, fb=2.7,
                                role="veg", query="Frozen Cut Green Beans 1kg",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="freezer", suits=frozenset("".split())),
    "Baby spinach": dict(kcal=23, p=2.9, c=3.6, f=0.4, fb=2.2,
                                role="veg", query="Baby Spinach 120g", pack=120,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Mushrooms, raw": dict(kcal=22, p=3.1, c=3.3, f=0.3, fb=1.0,
                                role="veg", query="Cup Mushrooms", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Carrot, raw": dict(kcal=41, p=0.9, c=10.0, f=0.2, fb=2.8,
                                role="veg", query="Carrots 1kg", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Cherry tomatoes": dict(kcal=18, p=0.9, c=3.9, f=0.2, fb=1.2,
                                role="veg", query="Cherry Tomatoes 250g", pack=250,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),

    # --- flavour bases --------------------------------------------------
    "Tomato passata": dict(kcal=35, p=1.6, c=6.5, f=0.3, fb=1.4,
                                role="sauce", query="Tomato Passata 700g", pack=700,
                                tags={"vegan", "gluten-free"}, aisle="pantry", serve_g=120, suits=frozenset("".split())),
    "Red curry paste": dict(kcal=110, p=3.0, c=13.0, f=5.0, fb=3.0,
                                role="sauce", query="Red Curry Paste", pack=200,
                                tags={"vegan"}, aisle="pantry", serve_g=25, suits=frozenset("".split())),
    "Light coconut milk": dict(kcal=73, p=0.7, c=2.8, f=6.8, fb=0.0,
                                role="sauce", query="Light Coconut Milk 400ml",
                                pack=400, tags={"vegan", "gluten-free"}, aisle="pantry", serve_g=70, suits=frozenset("".split())),
    "Soy sauce": dict(kcal=53, p=8.1, c=4.9, f=0.6, fb=0.8,
                                role="sauce", query="Soy Sauce 500ml", pack=500,
                                tags={"vegan"}, aisle="pantry", serve_g=15, suits=frozenset("".split())),

    # --- cuisine bases ---------------------------------------------------
    "Egg noodles, dry": dict(kcal=384, p=14.0, c=71.0, f=4.4, fb=3.3,
                                role="base", query="Egg Noodles 375g", pack=375,
                                tags={"vegetarian"}, aisle="pantry",
                                suits=frozenset("stirfry soup bowl".split())),
    "Soba noodles, dry": dict(kcal=336, p=14.0, c=70.0, f=0.7, fb=5.0,
                                role="base", query="Soba Buckwheat Noodles 270g",
                                pack=270, tags={"vegan"}, aisle="pantry",
                                suits=frozenset("stirfry soup bowl".split())),
    "Jasmine rice, dry": dict(kcal=356, p=7.0, c=79.0, f=0.6, fb=1.0,
                                role="base", query="Jasmine Rice 1kg", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                suits=frozenset("stirfry curry bowl".split())),
    "Polenta, dry": dict(kcal=362, p=8.1, c=79.0, f=1.4, fb=3.9,
                                role="base", query="Polenta 500g", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                suits=frozenset("ragu traybake".split())),
    "Corn tortillas": dict(kcal=218, p=5.7, c=45.0, f=2.9, fb=6.3,
                                role="base", query="Corn Tortillas 8 pack",
                                pack=320, tags={"vegan"}, aisle="pantry",
                                suits=frozenset("bowl traybake".split())),
    "Dried red lentils": dict(kcal=353, p=25.0, c=60.0, f=1.1, fb=31.0,
                                role="base", query="Red Lentils 500g", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                suits=frozenset("curry soup".split())),

    # --- cuisine vegetables ----------------------------------------------
    "Bok choy": dict(kcal=13, p=1.5, c=2.2, f=0.2, fb=1.0,
                                role="veg", query="Bok Choy", pack=400,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                suits=frozenset()),
    "Snow peas": dict(kcal=42, p=2.8, c=7.5, f=0.2, fb=2.6,
                                role="veg", query="Snow Peas", pack=200,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                suits=frozenset()),
    "Eggplant, raw": dict(kcal=25, p=1.0, c=6.0, f=0.2, fb=3.0,
                                role="veg", query="Eggplant", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                suits=frozenset()),
    "Cabbage, raw": dict(kcal=25, p=1.3, c=6.0, f=0.1, fb=2.5,
                                role="veg", query="Cabbage", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                suits=frozenset()),
    "Leek, raw": dict(kcal=61, p=1.5, c=14.0, f=0.3, fb=1.8,
                                role="veg", query="Leeks", pack=400,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                suits=frozenset()),

    # --- aromatics and finishing ------------------------------------------
    "Miso paste": dict(kcal=199, p=12.0, c=26.0, f=6.0, fb=5.0,
                                role="sauce", query="White Miso Paste 400g",
                                pack=400, tags={"vegan"}, aisle="pantry",
                                serve_g=20, suits=frozenset()),
    "Mirin": dict(kcal=258, p=0.2, c=43.0, f=0.0, fb=0.0,
                                role="sauce", query="Mirin Seasoning 250ml",
                                pack=250, tags={"vegan"}, aisle="pantry",
                                serve_g=15, suits=frozenset()),
    "Sesame oil": dict(kcal=884, p=0.0, c=0.0, f=100.0, fb=0.0,
                                role="fat", query="Sesame Oil 250ml", pack=250,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                serve_g=5, suits=frozenset()),
    "Oyster sauce": dict(kcal=51, p=2.0, c=11.0, f=0.3, fb=0.3,
                                role="sauce", query="Oyster Sauce 500ml",
                                pack=500, tags=set(), aisle="pantry",
                                serve_g=20, suits=frozenset()),
    "Fish sauce": dict(kcal=35, p=5.0, c=4.0, f=0.0, fb=0.0,
                                role="sauce", query="Fish Sauce 300ml", pack=300,
                                tags={"pescatarian"}, aisle="pantry",
                                serve_g=10, suits=frozenset()),
    "Garam masala": dict(kcal=379, p=14.0, c=45.0, f=15.0, fb=25.0,
                                role="sauce", query="Garam Masala 50g", pack=50,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                serve_g=6, suits=frozenset()),
    "Ground cumin": dict(kcal=375, p=18.0, c=44.0, f=22.0, fb=11.0,
                                role="sauce", query="Ground Cumin 40g", pack=40,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                serve_g=4, suits=frozenset()),
    "Dried oregano": dict(kcal=265, p=9.0, c=69.0, f=4.3, fb=42.0,
                                role="sauce", query="Dried Oregano 10g", pack=10,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                serve_g=2, suits=frozenset()),
    "Smoked paprika": dict(kcal=282, p=14.0, c=54.0, f=13.0, fb=35.0,
                                role="sauce", query="Smoked Paprika 40g", pack=40,
                                tags={"vegan", "gluten-free"}, aisle="pantry",
                                serve_g=4, suits=frozenset()),
    "Fresh ginger": dict(kcal=80, p=1.8, c=18.0, f=0.8, fb=2.0,
                                role="sauce", query="Fresh Ginger", pack=100,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                serve_g=8, suits=frozenset()),
    "Garlic": dict(kcal=149, p=6.4, c=33.0, f=0.5, fb=2.1,
                                role="sauce", query="Garlic Bulbs", pack=200,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                serve_g=6, suits=frozenset()),
    "Lemon": dict(kcal=29, p=1.1, c=9.3, f=0.3, fb=2.8,
                                role="sauce", query="Lemons", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce",
                                serve_g=25, suits=frozenset()),
    "Feta cheese": dict(kcal=264, p=14.0, c=4.1, f=21.0, fb=0.0,
                                role="sauce", query="Greek Feta 200g", pack=200,
                                tags={"vegetarian"}, aisle="fridge",
                                serve_g=30, suits=frozenset()),
    "Parmesan cheese": dict(kcal=431, p=38.0, c=4.1, f=29.0, fb=0.0,
                                role="sauce", query="Parmesan Cheese 200g",
                                pack=200, tags={"vegetarian"}, aisle="fridge",
                                serve_g=15, suits=frozenset()),
    "Tahini": dict(kcal=595, p=17.0, c=21.0, f=54.0, fb=9.0,
                                role="sauce", query="Tahini 385g", pack=385,
                                tags={"vegan"}, aisle="pantry",
                                serve_g=20, suits=frozenset()),
    "Butter": dict(kcal=717, p=0.9, c=0.1, f=81.0, fb=0.0,
                                role="fat", query="Butter 250g", pack=250,
                                tags={"vegetarian"}, aisle="fridge",
                                serve_g=10, suits=frozenset()),
    "Beef stock cubes": dict(kcal=250, p=12.0, c=25.0, f=12.0, fb=1.0,
                                role="sauce", query="Beef Stock Cubes", pack=60,
                                tags=set(), aisle="pantry",
                                serve_g=5, suits=frozenset()),
    "Extra virgin olive oil": dict(kcal=884, p=0.0, c=0.0, f=100.0, fb=0.0,
                                role="fat", query="Extra Virgin Olive Oil 1L",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="pantry", serve_g=10, suits=frozenset("".split())),
}

# Each template names the roles it needs and how to talk about the result.
TEMPLATES: Sequence[Dict[str, Any]] = (
    dict(id="traybake", name="{protein} tray bake with {base} and {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         steps=("Heat the oven to 200C.",
                "Toss the {veg} and {base} with the oil, salt and pepper.",
                "Spread on a lined tray and roast 20 minutes.",
                "Add the {protein}, roast a further 15-18 minutes until cooked through.",
                "Divide between containers and cool before refrigerating."),
         storage="Fridge up to 4 days, freezer up to 3 months.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir, then 1 more minute. Add a tablespoon of water first -- roasted veg dries out.",
             "From frozen: defrost overnight, or microwave at 30% for 6 minutes before reheating as above.",
             "Oven, if you want the edges crisp again: 180C for 12 minutes, uncovered.",
)),
    dict(id="stirfry", name="{protein} stir-fry with {base} and {veg}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Soy sauce",
         steps=("Cook the {base} to packet directions and set aside.",
                "Heat the oil in a wok over high heat.",
                "Sear the {protein} in batches, then remove.",
                "Stir-fry the {veg} 3-4 minutes until just tender.",
                "Return the {protein}, add the {sauce}, toss to coat.",
                "Fold through the {base} and portion out."),
         storage="Fridge up to 3 days. Freezing makes the vegetables limp.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir well, then 30-60 seconds more. Stirring matters here -- the sauce sits at the bottom.",
             "Better: 2 minutes in a hot pan with a splash of water, which keeps the vegetables with some bite.",
)),
    dict(id="ragu", name="{protein} ragu with {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         steps=("Heat the oil in a heavy pan.",
                "Brown the {protein}, breaking it up as it colours.",
                "Add the {veg} and cook 5 minutes until softened.",
                "Pour in the {sauce}, simmer 25 minutes until thickened.",
                "Cook the {base} and combine, or store separately."),
         storage="Fridge up to 4 days, freezer up to 3 months. Freeze the sauce and the base separately if you can.",
         reheat=(
             "Microwave from the fridge: 800W for 2.5 minutes, stir, then 1 more minute. Cover loosely -- tomato sauce spits.",
             "From frozen: 50% power for 8 minutes, breaking it up as it loosens, then full power for 2 minutes.",
)),
    dict(id="curry", name="{protein} curry with {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Red curry paste",
         steps=("Cook the {base} and set aside.",
                "Fry the {sauce} in the oil for 1 minute until fragrant.",
                "Add the {protein} and seal on all sides.",
                "Add the {veg} and coconut milk, simmer 15 minutes.",
                "Season, then portion over the {base}."),
         storage="Fridge up to 4 days, freezer up to 3 months. It improves overnight.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir, then 1 more minute. Cover loosely.",
             "If it has split or looks grainy, stir in a tablespoon of water off the heat and it will come back together.",
)),
    dict(id="bowl", name="{protein} and {base} bowl with {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         steps=("Cook the {base} and cool slightly.",
                "Season and pan-cook the {protein} until done, then slice.",
                "Steam or blanch the {veg} for 3 minutes.",
                "Layer base, {veg} and {protein} in containers.",
                "Dress with the oil and a squeeze of lemon before eating."),
         storage="Fridge up to 3 days. Best eaten cold or barely warm.",
         reheat=(
             "Microwave from the fridge: 800W for 90 seconds is plenty -- this is about taking the chill off, not cooking it again.",
             "Keep any dressing separate and add it after heating.",
)),
    dict(id="soup", name="{protein} and {veg} soup with {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         steps=("Soften the {veg} in the oil for 6-8 minutes.",
                "Add the {protein} and cook until coloured.",
                "Add the {sauce} and 1L of stock, simmer 20 minutes.",
                "Stir in the {base} and cook until tender.",
                "Cool fully before portioning into containers."),
         storage="Fridge up to 4 days, freezer up to 3 months.",
         reheat=(
             "Microwave from the fridge: 800W for 3 minutes, stir, then 1 more minute. Cover loosely and leave a vent.",
             "From frozen: 50% power for 10 minutes, stirring twice, then full power for 2 minutes. Check the middle is hot before eating.",
)),
)

# Minimum sensible amounts per serving, in grams.
_VEG_PER_SERVE = 150.0
_SAUCE_PER_SERVE = 80.0
_FAT_PER_SERVE = 10.0

# Keep the solver inside amounts a person would actually eat.
_PROTEIN_BOUNDS = (80.0, 350.0)

# Some proteins stop being plausible long before the general ceiling: 350g of
# egg is seven eggs in one serving. Where a real portion has a lower limit, it
# is named here and the shortfall is reported instead of hidden.
_PROTEIN_CEILING = {
    "Eggs": 200.0,
    "Firm tofu": 300.0,
    "Red kidney beans, drained": 260.0,
    "Chickpeas, drained": 260.0,
}
_BASE_BOUNDS = (30.0, 250.0)


# What a recipe "is", for grouping in a picker. Derived from the protein
# rather than stored, so it stays right if the ingredient list changes.
CATEGORIES = ("chicken", "beef", "pork", "lamb", "fish", "vegetarian", "other")

# Fish is checked before the red meats because "tuna steak" would otherwise
# match a bare "steak" and be filed under beef. Every beef ingredient contains
# the word "beef", so "steak" is not needed here at all.
_CATEGORY_WORDS = (
    ("chicken", ("chicken",)),
    ("fish", ("salmon", "tuna", "fish", "prawn", "barramundi")),
    ("beef", ("beef",)),
    ("pork", ("pork", "bacon", "ham")),
    ("lamb", ("lamb",)),
)


def category_for(recipe: Dict[str, Any]) -> str:
    """Group a recipe by its main protein."""
    protein = ""
    for item in recipe.get("ingredients") or []:
        if item.get("role") == "protein":
            protein = (item.get("food") or "").lower()
            break
    for label, words in _CATEGORY_WORDS:
        if any(w in protein for w in words):
            return label
    meta = INGREDIENTS.get(
        next((i["food"] for i in recipe.get("ingredients") or []
              if i.get("role") == "protein"), ""), {})
    tags = meta.get("tags") or set()
    if {"vegetarian", "vegan"} & tags:
        return "vegetarian"
    return "other"


def _by_role(role: str, diet: Optional[str], exclude: Sequence[str],
             template_id: Optional[str] = None) -> List[str]:
    """Ingredients filling a role, honouring diet, exclusions and template fit.

    `suits` keeps oats out of a stir-fry and tinned beans out of a tray bake.
    An empty `suits` means the ingredient works anywhere in its role.
    """
    banned = {e.strip().lower() for e in exclude if e and e.strip()}
    out = []
    for name, meta in INGREDIENTS.items():
        if meta["role"] != role:
            continue
        suits = meta.get("suits")
        if template_id is not None and suits and template_id not in suits:
            continue
        if template_id is not None and suits is not None and not suits                 and meta["role"] in ("protein", "base"):
            continue
        if name.lower() in banned or any(b in name.lower() for b in banned):
            continue
        if diet and diet != "any":
            tags = meta.get("tags") or set()
            if diet == "vegetarian" and not ({"vegetarian", "vegan"} & tags):
                continue
            if diet == "vegan" and "vegan" not in tags:
                continue
            if diet == "pescatarian" and not (
                    {"pescatarian", "vegetarian", "vegan"} & tags):
                continue
        out.append(name)
    return sorted(out)


# --------------------------------------------------------------------------
# Cuisines
# --------------------------------------------------------------------------
#
# A theme is not decoration: it decides what may go in the pan. Restricting the
# pools is the whole point -- without it a "Japanese" recipe cheerfully reaches
# for tomato passata and couscous, which is worse than offering no themes.
#
# `aromatics` are always added, in the quantities that make sense for them, and
# they are what actually makes a dish read as its cuisine. `finish` is a step
# appended to the method. `bases`/`veg`/`proteins`, where given, replace the
# general pool for that role.

CUISINES: Dict[str, Dict[str, Any]] = {
    "any": dict(label="No theme", templates=(), aromatics={}, finish=""),

    "italian": dict(
        label="Italian",
        templates=("ragu", "traybake", "soup", "bowl"),
        bases=("Wholemeal pasta, dry", "Polenta, dry", "White basmati rice, dry"),
        veg=("Zucchini, raw", "Capsicum, raw", "Mushrooms, raw",
             "Cherry tomatoes", "Eggplant, raw", "Baby spinach"),
        aromatics={"Garlic": 6, "Dried oregano": 2, "Parmesan cheese": 15,
                   "Extra virgin olive oil": 10},
        finish="Take it off the heat before stirring the parmesan through, "
               "or it turns stringy.",
    ),

    "japanese": dict(
        label="Japanese",
        templates=("stirfry", "bowl", "soup"),
        bases=("Jasmine rice, dry", "Soba noodles, dry", "Brown rice, dry"),
        veg=("Bok choy", "Snow peas", "Mushrooms, raw", "Cabbage, raw",
             "Carrot, raw", "Baby spinach"),
        aromatics={"Soy sauce": 15, "Mirin": 15, "Fresh ginger": 8,
                   "Sesame oil": 5},
        finish="Mix the soy, mirin and sesame oil first and add it at the very "
               "end -- boiling it dulls the flavour.",
    ),

    "chinese": dict(
        label="Chinese",
        templates=("stirfry", "soup", "bowl"),
        bases=("Jasmine rice, dry", "Egg noodles, dry", "White basmati rice, dry"),
        veg=("Bok choy", "Snow peas", "Capsicum, raw", "Cabbage, raw",
             "Mushrooms, raw", "Carrot, raw"),
        aromatics={"Soy sauce": 15, "Oyster sauce": 20, "Fresh ginger": 8,
                   "Garlic": 6, "Sesame oil": 5},
        finish="Get the pan properly hot before anything goes in; a cool wok "
               "steams the vegetables instead of searing them.",
    ),

    "thai": dict(
        label="Thai",
        templates=("curry", "stirfry", "soup"),
        bases=("Jasmine rice, dry", "Soba noodles, dry"),
        veg=("Capsicum, raw", "Snow peas", "Bok choy", "Eggplant, raw",
             "Green beans, frozen", "Carrot, raw"),
        aromatics={"Red curry paste": 25, "Light coconut milk": 70,
                   "Fish sauce": 10, "Lemon": 25},
        finish="Season at the end with fish sauce and a squeeze of lemon until "
               "it tastes balanced rather than just hot.",
    ),

    "indian": dict(
        label="Indian",
        templates=("curry", "soup", "traybake"),
        bases=("White basmati rice, dry", "Dried red lentils", "Brown rice, dry"),
        veg=("Cauliflower" if False else "Capsicum, raw", "Baby spinach",
             "Carrot, raw", "Eggplant, raw", "Green beans, frozen",
             "Sweet potato, raw"),
        aromatics={"Garam masala": 6, "Ground cumin": 4, "Fresh ginger": 8,
                   "Garlic": 6, "Light coconut milk": 70},
        finish="Fry the spices in the oil for a minute before anything else "
               "goes in -- raw garam masala tastes dusty.",
    ),

    "greek": dict(
        label="Greek",
        templates=("traybake", "bowl", "soup"),
        bases=("Potato, raw", "Couscous, dry", "White basmati rice, dry"),
        veg=("Zucchini, raw", "Capsicum, raw", "Cherry tomatoes",
             "Eggplant, raw", "Baby spinach", "Cucumber" if False else "Carrot, raw"),
        aromatics={"Lemon": 25, "Dried oregano": 2, "Garlic": 6,
                   "Feta cheese": 30, "Extra virgin olive oil": 10},
        finish="Crumble the feta over after cooking, and be generous with the "
               "lemon -- it is what makes it taste Greek rather than plain.",
    ),

    "mexican": dict(
        label="Mexican",
        templates=("bowl", "ragu", "traybake"),
        bases=("Corn tortillas", "White basmati rice, dry", "Brown rice, dry"),
        veg=("Capsicum, raw", "Cherry tomatoes", "Zucchini, raw",
             "Carrot, raw", "Baby spinach"),
        aromatics={"Ground cumin": 4, "Smoked paprika": 4, "Garlic": 6,
                   "Lemon": 25, "Extra virgin olive oil": 10},
        finish="Squeeze lemon over at the table. Warm the tortillas in a dry "
               "pan for twenty seconds a side.",
    ),

    "irish": dict(
        label="Irish",
        templates=("soup", "traybake"),
        bases=("Potato, raw", "Sweet potato, raw"),
        veg=("Carrot, raw", "Leek, raw", "Cabbage, raw", "Mushrooms, raw",
             "Green beans, frozen"),
        aromatics={"Beef stock cubes": 5, "Butter": 10, "Garlic": 6},
        finish="Let it sit twenty minutes off the heat before serving; a stew "
               "is always better slightly rested.",
    ),

    "middle-eastern": dict(
        label="Middle Eastern",
        templates=("traybake", "bowl", "soup"),
        bases=("Couscous, dry", "Dried red lentils", "White basmati rice, dry"),
        veg=("Eggplant, raw", "Capsicum, raw", "Zucchini, raw",
             "Cherry tomatoes", "Carrot, raw", "Baby spinach"),
        aromatics={"Ground cumin": 4, "Tahini": 20, "Lemon": 25, "Garlic": 6,
                   "Extra virgin olive oil": 10},
        finish="Loosen the tahini with water and lemon until it pours, then "
               "spoon it over rather than stirring it in.",
    ),
}


def cuisine_names() -> List[Dict[str, str]]:
    """The themes on offer, for a menu."""
    return [{"id": key, "label": meta["label"]} for key, meta in CUISINES.items()]


def _pool_for(role: str, cuisine: str, diet: Optional[str],
              exclude: Sequence[str], template_id: Optional[str]):
    """Ingredients for a role, narrowed to the cuisine where it defines a pool.

    Returns (pool, on_theme). `on_theme` is False when the theme's own list is
    empty for this template -- no Mexican base suits a ragu, for instance -- so
    the caller can try a different template instead of quietly serving polenta
    in a Mexican dish.
    """
    general = _by_role(role, diet, exclude, template_id)
    meta = CUISINES.get(cuisine or "any") or {}
    wanted = meta.get({"protein": "proteins", "base": "bases",
                       "veg": "veg"}.get(role, ""))
    if not wanted:
        return general, True
    narrowed = [name for name in wanted if name in general]
    return (narrowed, True) if narrowed else (general, False)


def _pick(options: List[str], seed: str, offset: int) -> Optional[str]:
    """Deterministic choice, so the same request reproduces the same recipe."""
    if not options:
        return None
    digest = hashlib.sha256(f"{seed}:{offset}".encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _macros(parts: Dict[str, float]) -> Dict[str, float]:
    """Total macros for a mapping of ingredient -> grams."""
    total = dict(kcal=0.0, p=0.0, c=0.0, f=0.0, fb=0.0)
    for name, grams in parts.items():
        meta = INGREDIENTS.get(name)
        if not meta:
            continue
        factor = grams / 100.0
        for key in total:
            total[key] += meta[key] * factor
    return {k: round(v, 1) for k, v in total.items()}


def _solve_quantities(
    protein: str, base: str, veg: str, extras: Dict[str, float],
    kcal_target: float, protein_target: float,
) -> Dict[str, float]:
    """Scale the protein to hit the protein target, then the base for calories."""
    fixed = dict(extras)
    fixed[veg] = _VEG_PER_SERVE

    p_per_100 = INGREDIENTS[protein]["p"] or 1.0
    fixed_protein = sum(
        INGREDIENTS[n]["p"] * g / 100.0 for n, g in fixed.items() if n in INGREDIENTS)
    need = max(0.0, protein_target - fixed_protein)
    ceiling = _PROTEIN_CEILING.get(protein, _PROTEIN_BOUNDS[1])
    protein_g = min(max(need / p_per_100 * 100.0, _PROTEIN_BOUNDS[0]), ceiling)

    running = dict(fixed)
    running[protein] = protein_g
    kcal_so_far = sum(
        INGREDIENTS[n]["kcal"] * g / 100.0 for n, g in running.items())

    kcal_per_100 = INGREDIENTS[base]["kcal"] or 1.0
    base_g = (kcal_target - kcal_so_far) / kcal_per_100 * 100.0
    base_g = min(max(base_g, _BASE_BOUNDS[0]), _BASE_BOUNDS[1])

    running[base] = base_g
    return {k: round(v) for k, v in running.items()}


def build_recipe(
    seed: str,
    servings: int = 4,
    kcal_per_serving: float = 600,
    protein_per_serving: float = 40,
    diet: str = "any",
    exclude: Sequence[str] = (),
    template_id: Optional[str] = None,
    offset: int = 0,
    cuisine: str = "any",
) -> Optional[Dict[str, Any]]:
    """Compose one recipe meeting the targets, or None if nothing fits."""
    theme = CUISINES.get(cuisine or "any") or CUISINES["any"]
    allowed = theme.get("templates") or ()
    templates = [t for t in TEMPLATES
                 if (not template_id or t["id"] == template_id)
                 and (not allowed or t["id"] in allowed)]
    if not templates:
        return None

    # Walk the allowed templates from a seeded start, keeping the first that
    # the theme can actually fill. Only if none can does an off-theme
    # substitution happen, and then it is recorded in the notes.
    start = int(hashlib.sha256(f"{seed}:t:{offset}".encode()).hexdigest()[:8], 16)
    template = templates[start % len(templates)]
    off_theme_roles: List[str] = []
    for step in range(len(templates)):
        candidate = templates[(start + step) % len(templates)]
        tid = candidate["id"]
        misses = [role for role in ("protein", "base", "veg")
                  if not _pool_for(role, cuisine, diet, exclude, tid)[1]]
        if not misses:
            template = candidate
            off_theme_roles = []
            break
        if step == 0:
            off_theme_roles = misses
    

    tid = template["id"]
    protein = _pick(_pool_for("protein", cuisine, diet, exclude, tid)[0],
                    seed, offset * 7 + 1)
    base = _pick(_pool_for("base", cuisine, diet, exclude, tid)[0],
                 seed, offset * 7 + 2)
    veg = _pick(_pool_for("veg", cuisine, diet, exclude, tid)[0],
                seed, offset * 7 + 3)
    if not (protein and base and veg):
        return None

    banned = {e.strip().lower() for e in exclude if e and e.strip()}
    extras: Dict[str, float] = {}
    # Always defined: the method text refers to it whichever branch runs.
    sauce_name = template.get("sauce")

    aromatics = theme.get("aromatics") or {}
    if aromatics:
        # The theme's pantry is what makes a dish read as its cuisine, so it
        # replaces the template's single generic sauce entirely.
        for name, grams in aromatics.items():
            if name not in INGREDIENTS:
                continue
            if any(b in name.lower() for b in banned):
                continue
            meta = INGREDIENTS[name]
            tags = meta.get("tags") or set()
            if diet == "vegan" and "vegan" not in tags:
                continue
            if diet == "vegetarian" and not ({"vegetarian", "vegan"} & tags):
                continue
            if diet == "pescatarian" and not (
                    {"pescatarian", "vegetarian", "vegan"} & tags):
                continue
            extras[name] = grams
    else:
        sauce_name = template.get("sauce")
        if "sauce" in template["roles"] and sauce_name in INGREDIENTS:
            if not any(b in sauce_name.lower() for b in banned):
                # A splash of soy is not the same quantity as a jar of passata.
                extras[sauce_name] = INGREDIENTS[sauce_name].get(
                    "serve_g", _SAUCE_PER_SERVE)

    if "fat" in template["roles"] and not any(
            INGREDIENTS.get(n, {}).get("role") == "fat" for n in extras):
        extras["Extra virgin olive oil"] = INGREDIENTS[
            "Extra virgin olive oil"].get("serve_g", _FAT_PER_SERVE)

    per_serve = _solve_quantities(
        protein, base, veg, extras, kcal_per_serving, protein_per_serving)
    macros = _macros(per_serve)

    # A low-density protein can hit its gram ceiling before the target, so say
    # so instead of presenting a miss as a match.
    notes = []
    if off_theme_roles:
        notes.append(
            f'No {theme.get("label", "themed")} '
            f'{" or ".join(off_theme_roles)} suited this dish, so a '
            f'general one was used.')
    if macros["p"] < protein_per_serving * 0.9:
        notes.append(
            f'{protein.split(",")[0]} tops out at {macros["p"]:.0f}g protein '
            f'per serving, short of the {protein_per_serving:.0f}g target.')
    if macros["kcal"] > kcal_per_serving * 1.15:
        notes.append(
            f'Comes in at {macros["kcal"]:.0f} kcal, above the '
            f'{kcal_per_serving:.0f} kcal target.')

    # With a theme the template's generic sauce is not in the pan, so the
    # method should name something that actually is.
    sauce_label = sauce_name or ""
    if aromatics:
        seasonings = [n for n in extras
                      if INGREDIENTS.get(n, {}).get("role") == "sauce"]
        sauce_label = seasonings[0] if seasonings else "the seasoning"

    labels = {"protein": protein.split(",")[0].lower(),
              "base": base.split(",")[0].lower(),
              "veg": veg.split(",")[0].lower(),
              "sauce": sauce_label.lower()}
    title = template["name"].format(**labels)
    title = title[0].upper() + title[1:]
    if theme.get("label") and cuisine not in ("", "any"):
        # "-style" is deliberate. These are generated approximations, not
        # regional recipes, and saying so is more honest than implying
        # otherwise.
        title = theme["label"] + "-style " + title[0].lower() + title[1:]

    return {
        "id": f"{template['id']}-{offset}",
        "name": title,
        "template": template["id"],
        "servings": servings,
        "diet": diet,
        "targets": {"kcalPerServing": kcal_per_serving,
                    "proteinPerServing": protein_per_serving},
        "perServing": macros,
        "notes": notes,
        "ingredients": [
            {
                "food": name,
                "gramsPerServing": grams,
                "gramsTotal": round(grams * servings),
                "role": INGREDIENTS[name]["role"],
                "query": INGREDIENTS[name]["query"],
                "pack": INGREDIENTS[name]["pack"],
                "aisle": INGREDIENTS[name].get("aisle", "pantry"),
            }
            for name, grams in sorted(
                per_serve.items(), key=lambda kv: -kv[1])
        ],
        "cuisine": cuisine if cuisine in CUISINES else "any",
        "cuisineLabel": theme.get("label", ""),
        "steps": ([s.format(**labels) for s in template["steps"]]
                  + ([theme["finish"]] if theme.get("finish") else [])),
        "storage": template.get("storage", ""),
        "protein": protein,
        "reheat": list(template.get("reheat", ())),
    }


def _finish(recipe: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Attach the derived category once the ingredients are known."""
    if recipe is not None:
        recipe["category"] = category_for(recipe)
    return recipe


# --------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------
#
# Protein and calories are solved for directly -- the protein sets the meat,
# the base fills the rest of the energy. The others cannot be solved the same
# way without turning this into a linear program, so they are scored instead:
# several candidates are built and the one that best satisfies everything asked
# for wins. Anything still missed is reported rather than hidden.

DEFAULT_TARGETS: Dict[str, Any] = {
    "kcal": 600.0,       # per serving, aim
    "protein": 40.0,     # per serving, at least
    "carbMax": None,     # per serving, at most
    "fatMax": None,      # per serving, at most
    "fibreMin": None,    # per serving, at least
    "sodiumAware": False,
}

# How badly each miss counts. Protein and energy are what people set first, so
# they dominate; the rest shape the choice between otherwise equal candidates.
_WEIGHTS = {"kcal": 1.0, "protein": 1.6, "carbMax": 0.9,
            "fatMax": 0.9, "fibreMin": 0.8}


def score_against(macros: Dict[str, float], targets: Dict[str, Any]) -> float:
    """Penalty for a recipe against the targets. Lower is better."""
    penalty = 0.0

    kcal = targets.get("kcal")
    if kcal:
        penalty += _WEIGHTS["kcal"] * abs(macros["kcal"] - kcal) / kcal

    protein = targets.get("protein")
    if protein:
        # Only a shortfall is a miss; more protein than asked for is fine.
        short = max(0.0, protein - macros["p"])
        penalty += _WEIGHTS["protein"] * short / protein

    carb_max = targets.get("carbMax")
    if carb_max:
        penalty += _WEIGHTS["carbMax"] * max(0.0, macros["c"] - carb_max) / carb_max

    fat_max = targets.get("fatMax")
    if fat_max:
        penalty += _WEIGHTS["fatMax"] * max(0.0, macros["f"] - fat_max) / fat_max

    fibre_min = targets.get("fibreMin")
    if fibre_min:
        penalty += _WEIGHTS["fibreMin"] * max(0.0, fibre_min - macros["fb"]) / fibre_min

    return penalty


def target_notes(macros: Dict[str, float], targets: Dict[str, Any]) -> List[str]:
    """Plain sentences for each target this recipe does not meet."""
    out: List[str] = []
    protein = targets.get("protein")
    if protein and macros["p"] < protein * 0.9:
        out.append(f'{macros["p"]:.0f}g protein, short of the '
                   f'{protein:.0f}g asked for.')
    kcal = targets.get("kcal")
    if kcal and macros["kcal"] > kcal * 1.15:
        out.append(f'{macros["kcal"]:.0f} kcal, above the {kcal:.0f} asked for.')
    if kcal and macros["kcal"] < kcal * 0.8:
        out.append(f'Only {macros["kcal"]:.0f} kcal, well under the '
                   f'{kcal:.0f} asked for.')
    carb_max = targets.get("carbMax")
    if carb_max and macros["c"] > carb_max * 1.1:
        out.append(f'{macros["c"]:.0f}g carbs, over the {carb_max:.0f}g limit.')
    fat_max = targets.get("fatMax")
    if fat_max and macros["f"] > fat_max * 1.1:
        out.append(f'{macros["f"]:.0f}g fat, over the {fat_max:.0f}g limit.')
    fibre_min = targets.get("fibreMin")
    if fibre_min and macros["fb"] < fibre_min * 0.9:
        out.append(f'{macros["fb"]:.0f}g fibre, under the {fibre_min:.0f}g '
                   f'asked for.')
    return out


def build_best(
    seed: str,
    targets: Optional[Dict[str, Any]] = None,
    servings: int = 4,
    diet: str = "any",
    exclude: Sequence[str] = (),
    cuisine: str = "any",
    tries: int = 14,
    start_offset: int = 0,
) -> Optional[Dict[str, Any]]:
    """Build several candidates and return the one that best fits the targets."""
    t = {**DEFAULT_TARGETS, **(targets or {})}
    best = None
    best_score = None
    for step in range(max(1, tries)):
        candidate = _finish(build_recipe(
            seed, servings, t["kcal"], t["protein"], diet, exclude,
            offset=start_offset + step, cuisine=cuisine))
        if candidate is None:
            continue
        penalty = score_against(candidate["perServing"], t)
        if best_score is None or penalty < best_score:
            best, best_score = candidate, penalty
        if penalty < 0.05:      # close enough; stop burning effort
            break
    if best is None:
        return None
    best["targets"] = {k: v for k, v in t.items() if v is not None}
    best["fit"] = round(max(0.0, 1.0 - (best_score or 0.0)), 2)
    # Replace the protein-only note with one line per unmet target.
    best["notes"] = ([n for n in best.get("notes", [])
                      if "tops out at" not in n and "kcal, above" not in n]
                     + target_notes(best["perServing"], t))
    return best


def build_plan(
    seed: str,
    meals: int = 4,
    servings: int = 4,
    kcal_per_serving: float = 600,
    protein_per_serving: float = 40,
    diet: str = "any",
    exclude: Sequence[str] = (),
    cuisine: str = "any",
    targets: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build several distinct recipes for one week's prep."""
    goals = {**DEFAULT_TARGETS, "kcal": kcal_per_serving,
             "protein": protein_per_serving, **(targets or {})}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    offset = 0
    # Try well past `meals` so exclusions cannot silently return a short plan.
    while len(out) < meals and offset < meals * 8:
        recipe = build_best(seed, goals, servings, diet, exclude, cuisine,
                            tries=4, start_offset=offset)
        offset += 4
        if not recipe:
            continue
        key = (recipe["template"], recipe["ingredients"][0]["food"])
        if key in seen:
            continue
        seen.add(key)
        recipe["id"] = f"{recipe['template']}-{len(out) + 1}"
        out.append(recipe)
    return out


def shopping_list(recipes: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Roll recipes up into one line per ingredient, in plan `shop` shape."""
    lines: Dict[str, Dict[str, Any]] = {}
    for recipe in recipes:
        for item in recipe["ingredients"]:
            entry = lines.setdefault(item["food"], {
                "woo": item["query"],
                "pack": item["pack"],
                "aisle": item.get("aisle") or _aisle_for(item["role"]),
                "grams": 0.0,
                "usedIn": [],
            })
            entry["grams"] += item["gramsTotal"]
            if recipe["name"] not in entry["usedIn"]:
                entry["usedIn"].append(recipe["name"])
    for entry in lines.values():
        entry["grams"] = round(entry["grams"])
        # How many packs to actually buy, rounded up.
        pack = entry.get("pack") or 0
        entry["packsNeeded"] = max(1, -(-entry["grams"] // pack)) if pack else None
    return lines


def _aisle_for(role: str) -> str:
    return {"protein": "meat", "base": "pantry", "veg": "produce",
            "sauce": "pantry", "fat": "pantry"}.get(role, "pantry")


def build_options(
    seed: str,
    count: int = 3,
    servings: int = 4,
    kcal_per_serving: float = 600,
    protein_per_serving: float = 40,
    diet: str = "any",
    exclude: Sequence[str] = (),
    avoid_proteins: Sequence[str] = (),
    cuisine: str = "any",
    targets: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Several genuinely different recipes for one slot.

    Two chicken dishes are not a choice, so options are separated by category
    rather than by exact ingredient -- chicken breast and chicken thigh are the
    same decision to someone deciding what to eat.
    """
    goals = {**DEFAULT_TARGETS, "kcal": kcal_per_serving,
             "protein": protein_per_serving, **(targets or {})}
    out: List[Dict[str, Any]] = []
    used = set()
    for name in avoid_proteins:
        used.add(category_for({"ingredients": [
            {"role": "protein", "food": name}]}))
    offset = 0
    while len(out) < count and offset < count * 16:
        recipe = build_best(seed, goals, servings, diet, exclude, cuisine,
                            tries=3, start_offset=offset)
        offset += 3
        if recipe is None:
            continue
        category = recipe.get("category") or "other"
        if category in used:
            continue
        used.add(category)
        recipe["option"] = chr(ord("A") + len(out))
        out.append(recipe)
    return out


def swaps_for(food: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Alternatives to one ingredient, with the nutritional consequence.

    A swap is only useful if you know what it costs you, so each option carries
    the change per 100g rather than just a name. Same role only -- offering rice
    instead of chicken is not a substitution, it is a different meal.
    """
    meta = INGREDIENTS.get(food)
    if not meta:
        return []

    role = meta["role"]
    tags = meta.get("tags") or set()
    options = []
    for name, other in INGREDIENTS.items():
        if name == food or other["role"] != role:
            continue
        options.append({
            "food": name,
            "query": other["query"],
            "pack": other["pack"],
            "aisle": other.get("aisle", "pantry"),
            "dKcal": round(other["kcal"] - meta["kcal"], 1),
            "dProtein": round(other["p"] - meta["p"], 1),
            "dCarb": round(other["c"] - meta["c"], 1),
            "dFat": round(other["f"] - meta["f"], 1),
            "dFibre": round(other["fb"] - meta["fb"], 1),
            # A swap that breaks the diet you are eating is not an option.
            "keepsVegan": "vegan" in (other.get("tags") or set()),
            "keepsVegetarian": bool(
                {"vegetarian", "vegan"} & (other.get("tags") or set())),
            "sameDiet": bool(tags & (other.get("tags") or set())) or not tags,
        })

    # Closest in calories first: the least disruptive substitution is usually
    # the one someone actually wants.
    options.sort(key=lambda o: abs(o["dKcal"]))
    return options[:limit]


def food_table() -> List[Dict[str, Any]]:
    """Every ingredient with its per-100g figures, for a reference view."""
    return [
        {
            "food": name,
            "role": meta["role"],
            "aisle": meta.get("aisle", "pantry"),
            "query": meta["query"],
            "pack": meta["pack"],
            "kcal": meta["kcal"], "p": meta["p"], "c": meta["c"],
            "f": meta["f"], "fb": meta["fb"],
            "tags": sorted(meta.get("tags") or []),
        }
        for name, meta in sorted(INGREDIENTS.items())
    ]
