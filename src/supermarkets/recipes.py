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
                                pack=700, tags={"vegetarian"}, cook="pan", aisle="fridge", suits=frozenset("bowl stirfry eggs shakshuka breakfasthash frittata".split())),
    "Lamb leg, raw, diced": dict(kcal=143, p=20.2, c=0.0, f=6.6, fb=0.0,
                                role="protein", query="Diced Lamb",
                                pack=500, tags={"meat"}, cook="simmer", aisle="meat", suits=frozenset("stew braise curry tagine traybake soup".split())),
    "Lamb mince, raw": dict(kcal=202, p=19.0, c=0.0, f=14.0, fb=0.0,
                                role="protein", query="Lamb Mince",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("ragu bake stew wrap soup".split())),
    "Pork mince, raw": dict(kcal=201, p=18.0, c=0.0, f=14.0, fb=0.0,
                                role="protein", query="Pork Mince",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("stirfry ragu noodles friedrice wrap".split())),
    "Turkey mince, lean, raw": dict(kcal=148, p=21.0, c=0.0, f=7.0, fb=0.0,
                                role="protein", query="Turkey Mince",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("ragu wrap bake skillet soup".split())),
    "Beef rump, raw": dict(kcal=131, p=23.0, c=0.0, f=4.1, fb=0.0,
                                role="protein", query="Beef Rump Steak",
                                pack=500, tags={"meat"}, cook="pan", aisle="meat", suits=frozenset("stirfry grill bowl salad noodles".split())),
    "Beef chuck, raw, diced": dict(kcal=160, p=21.0, c=0.0, f=8.5, fb=0.0,
                                role="protein", query="Diced Beef Chuck",
                                pack=500, tags={"meat"}, cook="simmer", aisle="meat", suits=frozenset("stew braise soup".split())),
    "Prawns, raw, peeled": dict(kcal=85, p=20.0, c=0.0, f=0.5, fb=0.0,
                                role="protein", query="Raw Peeled Prawns",
                                pack=400, tags={"fish", "pescatarian"}, cook="pan", aisle="meat", suits=frozenset("stirfry friedrice noodles curry bowl grill".split())),
    "White fish fillet, raw": dict(kcal=90, p=18.0, c=0.0, f=2.0, fb=0.0,
                                role="protein", query="Basa Fillets",
                                pack=500, tags={"fish", "pescatarian"}, cook="pan", aisle="meat", suits=frozenset("traybake bake chowder curry crumbed bowl".split())),
    "Haloumi": dict(kcal=321, p=22.0, c=2.0, f=25.0, fb=0.0,
                                role="protein", query="Haloumi Cheese",
                                pack=250, tags={"vegetarian"}, cook="pan", aisle="fridge", suits=frozenset("salad grill bowl traybake wrap".split())),
    "Cottage cheese": dict(kcal=98, p=11.0, c=3.4, f=4.3, fb=0.0,
                                role="protein", query="Cottage Cheese",
                                pack=500, tags={"vegetarian"}, cook="none", aisle="fridge", suits=frozenset("salad bowl bake yoghurtbowl eggs".split())),
    "Black beans, drained": dict(kcal=132, p=8.9, c=16.0, f=0.5, fb=8.7,
                                role="protein", query="Black Beans 400g tin",
                                pack=250, tags={"vegetarian", "vegan"}, cook="simmer", aisle="pantry", suits=frozenset("wrap bowl soup stew salad".split())),
    "Brown lentils, drained": dict(kcal=116, p=9.0, c=12.0, f=0.4, fb=8.0,
                                role="protein", query="Brown Lentils 400g tin",
                                pack=250, tags={"vegetarian", "vegan"}, cook="simmer", aisle="pantry", suits=frozenset("ragu soup stew curry salad bake".split())),
    "Greek yoghurt": dict(kcal=59, p=10.0, c=3.6, f=0.4, fb=0.0,
                                role="protein", query="Greek Style Natural Yoghurt 1kg",
                                pack=1000, tags={"vegetarian", "keto"}, cook="none", aisle="fridge", suits=frozenset("porridge yoghurtbowl smoothie salad".split())),
    "Milk, skim": dict(kcal=35, p=3.4, c=5.0, f=0.1, fb=0.0,
                                role="protein", query="Skim Milk 2L",
                                pack=2000, tags={"vegetarian"}, cook="none", aisle="fridge", suits=frozenset("porridge smoothie".split())),
    "Whey protein powder": dict(kcal=380, p=76.0, c=8.0, f=4.0, fb=1.0,
                                role="protein", query="Whey Protein Powder",
                                pack=1000, tags={"vegetarian", "keto"}, cook="none", aisle="pantry", suits=frozenset("smoothie yoghurtbowl porridge".split())),
    "Butter beans, drained": dict(kcal=110, p=7.0, c=15.0, f=0.5, fb=5.0,
                                role="protein", query="Butter Beans 400g tin",
                                pack=250, tags={"vegetarian", "vegan"}, cook="simmer", aisle="pantry", suits=frozenset("stew soup bake salad braise".split())),

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
                                pack=1000, tags={"vegan"}, aisle="pantry", suits=frozenset("porridge yoghurtbowl smoothie".split())),
    "Sweet potato, raw": dict(kcal=86, p=1.6, c=20.0, f=0.1, fb=3.0,
                                role="base", query="Gold Sweet Potato",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("traybake bowl curry soup breakfasthash frittata".split())),
    "Potato, raw": dict(kcal=77, p=2.0, c=17.0, f=0.1, fb=2.2,
                                role="base", query="Brushed Potatoes 2kg",
                                pack=2000, tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("traybake soup breakfasthash frittata".split())),
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
                                suits=frozenset("bowl traybake wrap".split())),
    "Wholegrain bread": dict(kcal=247, p=10.0, c=38.0, f=3.5, fb=6.5,
                                role="base", query="Wholegrain Bread Loaf",
                                pack=700, tags={"vegan"}, aisle="bakery", suits=frozenset("eggs shakshuka frittata wrap".split())),
    "Cauliflower rice": dict(kcal=25, p=1.9, c=3.0, f=0.3, fb=2.0,
                                role="base", query="Cauliflower Rice",
                                pack=500, tags={"vegan", "gluten-free", "keto"}, aisle="produce", suits=frozenset("stirfry curry bowl friedrice pilaf salad skillet".split())),
    "Zucchini noodles": dict(kcal=17, p=1.2, c=3.1, f=0.3, fb=1.0,
                                role="base", query="Zucchini Noodles",
                                pack=400, tags={"vegan", "gluten-free", "keto"}, aisle="produce", suits=frozenset("ragu bake noodles salad skillet stirfry".split())),
    "Konjac noodles": dict(kcal=8, p=0.2, c=3.0, f=0.1, fb=3.0,
                                role="base", query="Slendier Konjac Noodles",
                                pack=400, tags={"vegan", "gluten-free", "keto"}, aisle="pantry", suits=frozenset("noodles stirfry soup bowl".split())),
    "Quinoa, dry": dict(kcal=368, p=14.0, c=57.0, f=6.1, fb=7.0,
                                role="base", query="Quinoa 500g",
                                pack=500, tags={"vegan", "gluten-free"}, aisle="pantry", suits=frozenset("bowl salad pilaf traybake".split())),
    "Pearl barley, dry": dict(kcal=352, p=9.9, c=73.0, f=1.2, fb=15.6,
                                role="base", query="Pearl Barley 500g",
                                pack=500, tags={"vegan"}, aisle="pantry", suits=frozenset("soup stew braise pilaf chowder".split())),
    "Bulgur wheat, dry": dict(kcal=342, p=12.0, c=63.0, f=1.3, fb=18.0,
                                role="base", query="Burghul Wheat 500g",
                                pack=500, tags={"vegan"}, aisle="pantry", suits=frozenset("salad bowl pilaf tagine".split())),
    "Wholemeal wraps": dict(kcal=290, p=9.0, c=46.0, f=6.0, fb=6.0,
                                role="base", query="Wholemeal Wraps",
                                pack=500, tags={"vegan"}, aisle="bakery", suits=frozenset("wrap".split())),
    "Gnocchi": dict(kcal=158, p=3.5, c=32.0, f=1.0, fb=2.0,
                                role="base", query="Potato Gnocchi 500g",
                                pack=500, tags={"vegetarian"}, aisle="pantry", suits=frozenset("bake skillet ragu traybake frittata".split())),
    "Udon noodles": dict(kcal=130, p=4.5, c=27.0, f=0.5, fb=1.5,
                                role="base", query="Udon Noodles",
                                pack=400, tags={"vegan"}, aisle="pantry", suits=frozenset("noodles soup stirfry bowl".split())),
    "Rice noodles, dry": dict(kcal=364, p=6.0, c=82.0, f=0.6, fb=1.6,
                                role="base", query="Rice Stick Noodles 375g",
                                pack=375, tags={"vegan", "gluten-free"}, aisle="pantry", suits=frozenset("noodles stirfry soup bowl salad".split())),
    "Pumpkin, raw": dict(kcal=26, p=1.0, c=6.5, f=0.1, fb=0.5,
                                role="base", query="Butternut Pumpkin",
                                pack=1000, tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("traybake soup curry bake tagine stew chowder".split())),
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
    "Mixed berries, frozen": dict(kcal=48, p=1.0, c=8.0, f=0.3, fb=4.0,
                                role="veg", query="Frozen Mixed Berries", pack=500,
                                tags={"vegan", "gluten-free", "keto"}, aisle="freezer", suits=frozenset("porridge yoghurtbowl smoothie".split())),
    "Banana": dict(kcal=89, p=1.1, c=20.0, f=0.3, fb=2.6,
                                role="veg", query="Bananas", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("porridge yoghurtbowl smoothie".split())),
    "Avocado": dict(kcal=160, p=2.0, c=1.8, f=15.0, fb=6.7,
                                role="veg", query="Avocado", pack=200,
                                tags={"vegan", "gluten-free", "keto"}, aisle="produce", suits=frozenset("eggs salad bowl wrap shakshuka".split())),
    "Cauliflower, raw": dict(kcal=25, p=1.9, c=3.0, f=0.3, fb=2.0,
                                role="veg", query="Cauliflower", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Cucumber, raw": dict(kcal=15, p=0.7, c=3.6, f=0.1, fb=0.5,
                                role="veg", query="Continental Cucumber", pack=400,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("salad bowl wrap".split())),
    "Kale, raw": dict(kcal=49, p=4.3, c=8.8, f=0.9, fb=3.6,
                                role="veg", query="Kale", pack=200,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Peas, frozen": dict(kcal=81, p=5.4, c=14.0, f=0.4, fb=5.0,
                                role="veg", query="Frozen Peas", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="freezer", suits=frozenset("".split())),
    "Corn kernels": dict(kcal=86, p=3.3, c=19.0, f=1.2, fb=2.0,
                                role="veg", query="Corn Kernels", pack=420,
                                tags={"vegan", "gluten-free"}, aisle="pantry", suits=frozenset("".split())),
    "Asparagus, raw": dict(kcal=20, p=2.2, c=3.9, f=0.1, fb=2.1,
                                role="veg", query="Asparagus", pack=200,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Celery, raw": dict(kcal=16, p=0.7, c=3.0, f=0.2, fb=1.6,
                                role="veg", query="Celery", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Brown onion, raw": dict(kcal=40, p=1.1, c=9.3, f=0.1, fb=1.7,
                                role="veg", query="Brown Onions", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Tomato, raw": dict(kcal=18, p=0.9, c=3.9, f=0.2, fb=1.2,
                                role="veg", query="Tomatoes", pack=1000,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Brussels sprouts, raw": dict(kcal=43, p=3.4, c=9.0, f=0.3, fb=3.8,
                                role="veg", query="Brussels Sprouts", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
    "Silverbeet, raw": dict(kcal=19, p=1.8, c=3.7, f=0.2, fb=1.6,
                                role="veg", query="Silverbeet", pack=500,
                                tags={"vegan", "gluten-free"}, aisle="produce", suits=frozenset("".split())),
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
    "Peanut butter": dict(kcal=598, p=25.0, c=20.0, f=50.0, fb=6.0,
                                role="fat", query="Natural Peanut Butter",
                                pack=500, tags={"vegan", "keto"}, aisle="pantry", serve_g=15, suits=frozenset("porridge smoothie yoghurtbowl".split())),
    "Chia seeds": dict(kcal=486, p=17.0, c=42.0, f=31.0, fb=34.0,
                                role="fat", query="Chia Seeds",
                                pack=500, tags={"vegan", "keto"}, aisle="pantry", serve_g=12, suits=frozenset("porridge yoghurtbowl smoothie".split())),
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="oven", active_min=8, passive_min=35,
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=12, passive_min=0,
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=25,
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=8, passive_min=15,
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=0,
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
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=20,
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
    dict(id="skillet", name="{protein} skillet with {base} and {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=8, passive_min=8,
         steps=("Heat the oil in a wide pan over medium-high heat.",
                "Brown the {protein} on all sides and move it to a plate.",
                "Cook the {veg} in the same pan for 5 minutes, scraping up what stuck.",
                "Return the {protein} with the cooked {base} and a splash of water.",
                "Cover and cook 8 minutes, then rest off the heat before portioning."),
         storage="Fridge up to 4 days, freezer up to 2 months.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir, then 1 more minute.",
             "In a pan is better if you have five minutes -- the browned edges come back.",
)),
    dict(id="bake", name="Baked {protein} with {base} and {veg}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="oven", active_min=10, passive_min=35,
         steps=("Heat the oven to 190C.",
                "Par-cook the {base} for half its packet time and drain.",
                "Toss the {veg} and {base} with the {sauce} and the oil in a baking dish.",
                "Nestle the {protein} in, cover with foil and bake 25 minutes.",
                "Uncover and bake 10 minutes more to colour the top.",
                "Cool to room temperature before it goes in containers."),
         storage="Fridge up to 4 days, freezer up to 3 months. It slices better cold.",
         reheat=(
             "Microwave from the fridge: 800W for 2.5 minutes, then 1 more minute. Cover loosely.",
             "Oven, if the top matters: 180C for 15 minutes, foil on for the first ten.",
             "From frozen: defrost overnight, otherwise the middle stays cold while the edge boils.",
)),
    dict(id="stew", name="{protein} stew with {veg} and {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=12, passive_min=70,
         steps=("Heat the oil in a heavy pot and brown the {protein} in batches.",
                "Soften the {veg} in the same pot for 6 minutes.",
                "Return the {protein}, add the {sauce} and enough stock to cover.",
                "Simmer gently, lid ajar, for 50 minutes until the {protein} gives way.",
                "Add the {base} for the last 20 minutes.",
                "Cool uncovered before portioning -- a hot lid makes it watery."),
         storage="Fridge up to 4 days, freezer up to 3 months. Better on the second day.",
         reheat=(
             "Microwave from the fridge: 800W for 3 minutes, stir, then 1 more minute.",
             "From frozen: 50% power for 10 minutes, breaking it up twice, then 2 minutes full.",
)),
    dict(id="noodles", name="{protein} noodles with {veg}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Soy sauce",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=0,
         steps=("Cook the {base} to just under packet time and rinse in cold water.",
                "Heat the oil in a wok until it shimmers.",
                "Sear the {protein} hard for 2 minutes, then push it to one side.",
                "Add the {veg} and stir-fry 3 minutes.",
                "Add the noodles and the {sauce}, tossing until everything is coated.",
                "Portion straight away; noodles left in the wok keep cooking."),
         storage="Fridge up to 3 days. Freezing turns the noodles to paste.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir hard, then 45 seconds.",
             "Loosen with a tablespoon of water first -- cold noodles clump into a brick.",
)),
    dict(id="friedrice", name="{protein} fried rice with {veg}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Soy sauce",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=8, passive_min=0,
         steps=("Cook the {base} the day before and chill it; warm rice steams instead of frying.",
                "Heat the oil in a wok over the highest heat you have.",
                "Cook the {protein} through and set it aside.",
                "Fry the {veg} for 2 minutes, then add the cold {base} and press it flat.",
                "Leave it 30 seconds between tosses so it catches.",
                "Return the {protein}, add the {sauce}, toss once and take it off."),
         storage="Fridge up to 3 days. Cool it fast and refrigerate within an hour -- cooked rice is the one to be careful with.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes, stir, then 1 more minute until steaming right through.",
             "Reheat once only, and never from lukewarm.",
)),
    dict(id="salad", name="{protein} salad with {base} and {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=12, passive_min=0,
         steps=("Cook the {base} and spread it out to cool quickly.",
                "Season the {protein} and cook it through, then slice.",
                "Cut the {veg} small enough to eat with a fork.",
                "Combine everything with the oil, lemon, salt and pepper.",
                "Keep the dressing separate if it is going more than a day."),
         storage="Fridge up to 3 days undressed, one day dressed. Not for the freezer.",
         reheat=(
             "Meant to be eaten cold, straight from the fridge.",
             "If you want it warm, 60 seconds at 800W is enough -- any more and the vegetables collapse.",
)),
    dict(id="wrap", name="{protein} wraps with {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=0,
         steps=("Cook the {protein} with the oil and plenty of seasoning.",
                "Shred or slice it and let it cool.",
                "Prepare the {veg} raw or lightly charred, whichever you prefer.",
                "Store the filling and the {base} apart -- a wrap assembled early goes soggy.",
                "Warm the {base} for twenty seconds a side and fill it when you eat."),
         storage="Filling: fridge up to 4 days, freezer up to 2 months. Wraps: as the packet says.",
         reheat=(
             "Microwave the filling from the fridge: 800W for 90 seconds, stir, 30 seconds more.",
             "Warm the wrap in a dry pan while the filling heats. A microwaved wrap goes leathery.",
)),
    dict(id="grill", name="Grilled {protein} skewers with {base} and {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=12, passive_min=0,
         steps=("Cut the {protein} into even pieces and toss with the oil and seasoning.",
                "Thread onto skewers, leaving a gap between pieces so they colour.",
                "Grill or pan-sear 3-4 minutes a side until charred at the edges.",
                "Cook the {base} and char the {veg} in the same pan.",
                "Rest 5 minutes before boxing, or the juices end up in the container."),
         storage="Fridge up to 3 days, freezer up to 2 months.",
         reheat=(
             "Microwave from the fridge: 800W for 90 seconds. Longer and lean meat goes tough.",
             "Under a hot grill for 3 minutes is better if the char is the point.",
)),
    dict(id="braise", name="Braised {protein} with {veg} and {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="oven", active_min=15, passive_min=90,
         steps=("Heat the oven to 160C.",
                "Brown the {protein} hard in an ovenproof pot and set it aside.",
                "Soften the {veg} in the same pot for 8 minutes.",
                "Return the {protein} with the {sauce} and stock to come halfway up.",
                "Lid on, oven for 1 hour 30 minutes until it pulls apart.",
                "Cook the {base} fresh, and store it apart from the braise."),
         storage="Fridge up to 4 days, freezer up to 3 months. Freeze it in its own liquid.",
         reheat=(
             "Microwave from the fridge: 800W for 3 minutes, stir, then 1 more minute.",
             "It thickens in the fridge -- a splash of water before reheating brings it back.",
)),
    dict(id="pilaf", name="{protein} pilaf with {veg}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=7, passive_min=20,
         steps=("Toast the dry {base} in the oil for 2 minutes until it smells nutty.",
                "Add the {veg} and cook 3 minutes.",
                "Pour in twice the volume of stock, bring to a simmer and lid on.",
                "Cook the {protein} separately and fold it through at the end.",
                "Rest 10 minutes off the heat with the lid on, then fork it apart."),
         storage="Fridge up to 3 days. Cool it fast -- it is mostly cooked grain.",
         reheat=(
             "Microwave from the fridge: 800W for 2 minutes with a tablespoon of water, stir, then 1 minute.",
             "Cover it. Uncovered pilaf dries into gravel.",
)),
    dict(id="chowder", name="{protein} chowder with {base}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=10, passive_min=15,
         steps=("Soften the {veg} in the oil for 8 minutes without colouring them.",
                "Add the diced {base} and 800ml of stock, simmer until tender.",
                "Blend about a third of the pot and stir it back in to thicken.",
                "Add the {protein} and cook gently 5 minutes -- it should not boil.",
                "Season hard; a chowder needs more salt than you expect."),
         storage="Fridge up to 3 days. Freezes acceptably but the texture loosens.",
         reheat=(
             "Microwave from the fridge: 800W for 2.5 minutes, stir, then 1 more minute.",
             "Gently. A boiled chowder splits and no amount of stirring fixes it.",
)),
    dict(id="frittata", name="{protein} frittata with {veg} and {base}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="oven", active_min=10, passive_min=15,
         steps=("Heat the oven to 180C.",
                "Cook the {base} and the {veg} in an ovenproof pan with the oil.",
                "Add the cooked {protein} and spread everything level.",
                "Pour beaten egg over to just cover, and cook 3 minutes on the hob.",
                "Bake 15 minutes until set in the middle, then cool in the pan.",
                "Cut into portions once completely cold."),
         storage="Fridge up to 4 days. Freezer up to 1 month, wrapped in slices.",
         reheat=(
             "Microwave from the fridge: 800W for 60-75 seconds. It only needs warming.",
             "Good cold, which is the point of making it.",
)),
    dict(id="tagine", name="{protein} tagine with {veg} and {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=8, passive_min=45,
         steps=("Fry the spices in the oil for a minute until they smell toasted.",
                "Add the {protein} and colour it on all sides.",
                "Add the {veg} and the {sauce} with 300ml of stock.",
                "Simmer covered for 45 minutes, stirring now and then.",
                "Cook the {base} and serve it under the tagine.",
                "Cool fully before it goes in containers."),
         storage="Fridge up to 4 days, freezer up to 3 months.",
         reheat=(
             "Microwave from the fridge: 800W for 2.5 minutes, stir, then 1 more minute.",
             "From frozen: 50% for 8 minutes, then full power for 2.",
)),
    dict(id="porridge", name="{base} porridge with {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="assemble", active_min=5, passive_min=0,
         steps=("Put the {base} and the {protein} in a pan over medium heat.",
                "Stir until it thickens, about 5 minutes.",
                "Fold the {veg} through at the end so it keeps its shape.",
                "Top with the seeds or nut butter.",
                "For the week ahead, portion it cold into jars and it sets overnight."),
         storage="Fridge up to 4 days made ahead. It sets firm and loosens when warmed.",
         reheat=(
             "Microwave from the fridge: 800W for 90 seconds with a splash of milk, stir, then 30 seconds.",
             "Good cold straight from the jar, which is the point of making it the night before.",
)),
    dict(id="yoghurtbowl", name="{protein} bowl with {veg} and {base}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="assemble", active_min=3, passive_min=0,
         steps=("Toast the {base} in a dry pan for 3 minutes until it smells nutty.",
                "Spoon the {protein} into jars or containers.",
                "Add the {veg} on top.",
                "Keep the toasted {base} and the seeds separate until you eat it, or it goes soft.",
                "Assembles in twenty seconds in the morning."),
         storage="Fridge up to 4 days. Keep anything crunchy in its own container.",
         reheat=(
             "Not reheated -- eaten cold from the fridge.",
             "If the fruit was frozen, it thaws overnight and makes its own syrup.",
)),
    dict(id="smoothie", name="{veg} and {protein} smoothie with {base}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="blender", active_min=5, passive_min=0,
         steps=("Put the {veg}, {protein} and {base} in the blender.",
                "Add 200ml of water or milk and the nut butter or seeds.",
                "Blend 45 seconds until there is nothing left to chew.",
                "Pour into a bottle and refrigerate.",
                "For the week, freeze the fruit in bags and blend each morning."),
         storage="Fridge up to 2 days; it separates but stirs back together. Freeze the fruit portions instead for longer.",
         reheat=(
             "Drunk cold. Shake it before opening -- it settles.",
             "If it has thickened overnight, a splash of water brings it back.",
)),
    dict(id="eggs", name="{protein} on {base} with {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=8, passive_min=0,
         steps=("Cook the {veg} in the butter or oil until soft, about 4 minutes.",
                "Add the {protein} and cook gently, stirring, until just set.",
                "Take it off the heat while it still looks slightly underdone; it carries on cooking.",
                "Toast the {base} and pile it on.",
                "For the week, cook the vegetables ahead and do the eggs fresh -- they take two minutes."),
         storage="Vegetables: fridge up to 4 days. Eggs are best cooked the morning you eat them.",
         reheat=(
             "Microwave the vegetables from the fridge: 800W for 60 seconds, then cook the eggs into them.",
             "Reheated scrambled egg goes rubbery. This is the one worth doing fresh.",
)),
    dict(id="shakshuka", name="{protein} baked in {veg} with {base}",
         roles=("protein", "base", "veg", "sauce", "fat"), sauce="Tomato passata",
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=12, passive_min=10,
         steps=("Soften the {veg} in the oil for 8 minutes.",
                "Add the {sauce} and simmer until it thickens, about 10 minutes.",
                "Make wells and break the {protein} into them.",
                "Cover and cook 6-8 minutes until the whites set.",
                "Serve with the {base}. The sauce keeps all week; the eggs go in fresh."),
         storage="Sauce: fridge up to 4 days, freezer up to 3 months. Cook the eggs into it when you eat.",
         reheat=(
             "Reheat the sauce in a pan, make the wells, and crack the eggs in. Eight minutes start to finish.",
             "Microwave from the fridge: 800W for 2 minutes for the sauce alone.",
)),
    dict(id="breakfasthash", name="{protein} and {veg} hash with {base}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="stovetop", active_min=14, passive_min=0,
         steps=("Dice the {base} small and par-cook it for 6 minutes.",
                "Fry it in the oil, pressed flat, until the edges crisp.",
                "Add the {veg} and cook 4 minutes.",
                "Add the {protein} and cook through.",
                "Season well and cool before portioning."),
         storage="Fridge up to 4 days, freezer up to 2 months.",
         reheat=(
             "A hot dry pan for 4 minutes is what brings the crisp edges back.",
             "Microwave from the fridge: 800W for 2 minutes, stir, then 45 seconds. It will be soft, not crisp.",
)),
    dict(id="crumbed", name="Crumbed {protein} with {base} and {veg}",
         roles=("protein", "base", "veg", "fat"), sauce=None,
         # Hands-on minutes, minutes it needs nothing from you, and what
         # has to be free for it to run -- an oven or a stovetop hosts one
         # dish at a time, everything else runs alongside anything.
         device="oven", active_min=12, passive_min=20,
         steps=("Heat the oven to 200C and put a tray in to get hot.",
                "Coat the {protein} in flour, then egg, then breadcrumbs, pressing them on.",
                "Lay it on the hot tray with the oil and bake 20 minutes, turning once.",
                "Roast or steam the {veg} alongside.",
                "Cook the {base} and keep it separate so the crumb stays dry."),
         storage="Fridge up to 3 days. Freezer up to 2 months, crumbed and uncooked is better.",
         reheat=(
             "Oven or air fryer, 190C for 8 minutes. This is the one dish where it matters.",
             "The microwave works but the crumb goes soft: 800W for 90 seconds if you are in a hurry.",
)),
)

# Nobody eats chicken breast ragu at seven in the morning. Each shape says when
# it belongs, so a day is planned as a breakfast, a lunch and a dinner rather
# than three interchangeable dinners.
#
# The split is not fussy: most savoury dishes work for either lunch or dinner,
# a salad or a wrap leans to lunch, and a braise that takes ninety minutes is a
# dinner. What matters is that breakfast is its own set.
_MEAL_SLOTS: Dict[str, Sequence[str]] = {
    "porridge": ("breakfast",),
    "yoghurtbowl": ("breakfast",),
    "smoothie": ("breakfast",),
    "eggs": ("breakfast",),
    "shakshuka": ("breakfast",),
    "breakfasthash": ("breakfast",),
    "salad": ("lunch",),
    "wrap": ("lunch",),
    "frittata": ("breakfast", "lunch"),
    "bowl": ("lunch", "dinner"),
    "soup": ("lunch", "dinner"),
    "noodles": ("lunch", "dinner"),
    "friedrice": ("lunch", "dinner"),
    "stirfry": ("lunch", "dinner"),
    "skillet": ("lunch", "dinner"),
    "chowder": ("lunch", "dinner"),
    "pilaf": ("lunch", "dinner"),
    "traybake": ("dinner",),
    "ragu": ("dinner",),
    "curry": ("dinner",),
    "bake": ("dinner",),
    "stew": ("dinner",),
    "braise": ("dinner",),
    "grill": ("dinner",),
    "tagine": ("dinner",),
    "crumbed": ("dinner",),
}

MEALS: Sequence[str] = ("breakfast", "lunch", "dinner")

# Shapes where even the vegetable has to name the dish. Everything else is
# already governed by proteins and bases naming what they suit; this exists so
# that "any vegetable works anywhere" does not put broccoli in the porridge.
# Savoury breakfasts are deliberately not on this list -- a shakshuka wants
# ordinary vegetables, and requiring them to opt in left it with none.
_OPT_IN = frozenset(("porridge", "yoghurtbowl", "smoothie"))


def meals_for(template_id: str) -> Sequence[str]:
    """When this dish belongs. Unlisted shapes are treated as a main."""
    return _MEAL_SLOTS.get(template_id, ("lunch", "dinner"))


def templates_for_meal(meal: Optional[str]) -> List[str]:
    if not meal or meal == "any":
        return [t["id"] for t in TEMPLATES]
    return [t["id"] for t in TEMPLATES if meal in meals_for(t["id"])]


# A new dish shape starts with no ingredients willing to go in it: every
# protein and base lists the templates it suits, and none of them had heard of
# a tagine. Saying which existing shape each new one cooks like is both shorter
# than editing every list and truer -- a braise really does take the same cuts
# as a stew.
_COOKS_LIKE: Dict[str, Sequence[str]] = {
    "skillet": ("stirfry", "ragu"),
    "bake": ("traybake", "ragu"),
    "stew": ("soup", "curry"),
    "noodles": ("stirfry",),
    "friedrice": ("stirfry",),
    "salad": ("bowl",),
    "grill": ("traybake", "stirfry"),
    "braise": ("soup", "curry"),
    "pilaf": ("curry", "bowl"),
    "chowder": ("soup",),
    "tagine": ("curry",),
    "crumbed": ("traybake", "bowl"),
}

for _meta in INGREDIENTS.values():
    _suits = _meta.get("suits")
    if _suits:
        _meta["suits"] = frozenset(_suits) | {
            new for new, like in _COOKS_LIKE.items()
            if any(old in _suits for old in like)}
del _meta, _suits


# Keto is a carbohydrate ceiling, so what belongs in it is decided by the
# numbers already recorded rather than by a hand-kept list that would drift out
# of step the moment an ingredient was added.
#
# The measure is net carbohydrate -- what is left after the fibre, which is not
# absorbed -- because that is what the diet actually counts. Counting the total
# instead gets it wrong in both directions: it throws out broccoli at 7g and
# lets carrot in at 9.6g, when after fibre they are 4.4g and 6.8g.
KETO_NET_CARB_LIMIT = 6.0        # grams per 100g of an ingredient
# A serving has to add up as well as its parts: three hundred grams of a
# vegetable that is inside the limit can still put the plate outside it.
KETO_CARBS_PER_SERVING = 20.0


def net_carbs(macros: Dict[str, Any]) -> float:
    return max(0.0, (macros.get("c") or 0.0) - (macros.get("fb") or 0.0))


for _name, _meta in INGREDIENTS.items():
    if (net_carbs(_meta) <= KETO_NET_CARB_LIMIT
            and _meta["role"] in ("protein", "base", "veg", "fat")):
        _meta["tags"] = set(_meta.get("tags") or ()) | {"keto"}
del _name, _meta


# Things you buy by weight or by the each rather than in a packet. Their `pack`
# figure is a costing unit -- what a kilo of it costs -- and printing it on a
# shopping list as "2 packs, 1000g each" is nonsense: nobody has ever picked up
# a one-kilogram pack of cauliflower. For these the list says how much to buy,
# not how many to buy.
LOOSE = frozenset([
    "Capsicum, raw", "Zucchini, raw", "Carrot, raw", "Pumpkin, raw",
    "Eggplant, raw", "Cabbage, raw", "Banana", "Avocado", "Cauliflower, raw",
    "Cucumber, raw", "Celery, raw", "Brown onion, raw", "Tomato, raw",
    "Leek, raw", "Broccoli, raw", "Sweet potato, raw", "Potato, raw",
    "Brussels sprouts, raw", "Silverbeet, raw", "Kale, raw", "Bok choy",
    "Asparagus, raw", "Lemon", "Garlic",
])

for _name, _meta in INGREDIENTS.items():
    if _name in LOOSE:
        _meta["loose"] = True
del _name, _meta


# Minimum sensible amounts per serving, in grams.
_VEG_PER_SERVE = 150.0
# As much veg as anyone will put in one container. Past this the honest answer
# is that the fibre floor is not reachable in this many meals, and the recipe
# says so in its notes rather than proposing a kilo of broccoli.
_VEG_CEILING = 400.0
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
        # An ingredient with no `suits` works anywhere in its role, which is
        # right for a vegetable in a savoury dish and badly wrong at breakfast:
        # it puts broccoli in the porridge. Breakfast shapes take only what
        # names them.
        if template_id in _OPT_IN and template_id not in (suits or ()):
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
            if diet == "keto" and "keto" not in tags:
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
        templates=("ragu", "traybake", "soup", "bowl", "bake", "skillet",
                   "salad", "frittata", "braise"),
        bases=("Wholemeal pasta, dry", "Polenta, dry", "White basmati rice, dry",
               "Gnocchi", "Potato, raw"),
        veg=("Zucchini, raw", "Capsicum, raw", "Mushrooms, raw",
             "Cherry tomatoes", "Eggplant, raw", "Baby spinach",
             "Brown onion, raw", "Celery, raw", "Tomato, raw", "Silverbeet, raw"),
        proteins=("Beef mince, lean, raw", "Chicken breast, raw",
                  "Chicken thigh fillet, raw, skinless", "Pork mince, raw",
                  "Turkey mince, lean, raw", "Beef chuck, raw, diced",
                  "White fish fillet, raw", "Brown lentils, drained",
                  "Butter beans, drained", "Eggs", "Prawns, raw, peeled"),
        aromatics={"Garlic": 6, "Dried oregano": 2, "Parmesan cheese": 15,
                   "Extra virgin olive oil": 10},
        dishes={"ragu": "{protein} ragu with {base}",
                "bake": "{protein} al forno with {base} and {veg}",
                "soup": "{protein} and {veg} minestrone with {base}",
                "braise": "{protein} spezzatino with {veg} and {base}",
                "salad": "{protein} and {base} insalata with {veg}",
                "skillet": "{protein} and {veg} padella with {base}"},
        finish="Take it off the heat before stirring the parmesan through, "
               "or it turns stringy.",
    ),

    "japanese": dict(
        label="Japanese",
        templates=("stirfry", "bowl", "soup", "noodles", "friedrice",
                   "grill", "crumbed", "salad"),
        bases=("Jasmine rice, dry", "Soba noodles, dry", "Brown rice, dry",
               "Udon noodles", "White basmati rice, dry"),
        veg=("Bok choy", "Snow peas", "Mushrooms, raw", "Cabbage, raw",
             "Carrot, raw", "Baby spinach", "Broccoli, raw", "Peas, frozen",
             "Cucumber, raw", "Brown onion, raw"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Salmon fillet, raw", "Tuna steak, raw", "Firm tofu",
                  "Prawns, raw, peeled", "Pork loin, raw", "Beef rump, raw",
                  "Eggs", "White fish fillet, raw"),
        aromatics={"Soy sauce": 15, "Mirin": 15, "Fresh ginger": 8,
                   "Sesame oil": 5},
        dishes={"bowl": "{protein} donburi with {veg}",
                "noodles": "{protein} yakisoba with {veg}",
                "soup": "{protein} and {veg} miso broth with {base}",
                "grill": "{protein} yakitori with {base} and {veg}",
                "crumbed": "{protein} katsu with {base} and {veg}",
                "friedrice": "{protein} chahan with {veg}",
                "stirfry": "Teriyaki {protein} with {base} and {veg}",
                "salad": "{protein} and {veg} sunomono with {base}"},
        finish="Mix the soy, mirin and sesame oil first and add it at the very "
               "end -- boiling it dulls the flavour.",
    ),

    "chinese": dict(
        label="Chinese",
        templates=("stirfry", "soup", "bowl", "noodles", "friedrice",
                   "braise", "skillet"),
        bases=("Jasmine rice, dry", "Egg noodles, dry", "White basmati rice, dry",
               "Rice noodles, dry", "Udon noodles", "Brown rice, dry"),
        veg=("Bok choy", "Snow peas", "Capsicum, raw", "Cabbage, raw",
             "Mushrooms, raw", "Carrot, raw", "Broccoli, raw",
             "Brown onion, raw", "Celery, raw", "Baby spinach"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Pork loin, raw", "Pork mince, raw", "Beef rump, raw",
                  "Beef chuck, raw, diced", "Firm tofu", "Prawns, raw, peeled",
                  "Eggs", "Tuna steak, raw"),
        aromatics={"Soy sauce": 15, "Oyster sauce": 20, "Fresh ginger": 8,
                   "Garlic": 6, "Sesame oil": 5},
        dishes={"noodles": "{protein} lo mein with {veg}",
                "braise": "Red-braised {protein} with {veg} and {base}",
                "soup": "{protein} and {veg} broth with {base}",
                "skillet": "{protein} and {veg} claypot with {base}"},
        finish="Get the pan properly hot before anything goes in; a cool wok "
               "steams the vegetables instead of searing them.",
    ),

    "thai": dict(
        label="Thai",
        templates=("curry", "stirfry", "soup", "noodles", "salad",
                   "friedrice", "skillet"),
        bases=("Jasmine rice, dry", "Soba noodles, dry", "Rice noodles, dry",
               "Brown rice, dry"),
        veg=("Capsicum, raw", "Snow peas", "Bok choy", "Eggplant, raw",
             "Green beans, frozen", "Carrot, raw", "Cabbage, raw",
             "Broccoli, raw", "Brown onion, raw", "Cucumber, raw"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Firm tofu", "Prawns, raw, peeled", "Pork mince, raw",
                  "Beef rump, raw", "White fish fillet, raw", "Eggs"),
        aromatics={"Red curry paste": 25, "Light coconut milk": 70,
                   "Fish sauce": 10, "Lemon": 25},
        dishes={"curry": "{protein} red curry with {base}",
                "noodles": "{protein} pad see ew with {veg}",
                "soup": "{protein} tom yum with {veg}",
                "salad": "{protein} larb salad with {veg} and {base}",
                "friedrice": "{protein} khao pad with {veg}"},
        finish="Season at the end with fish sauce and a squeeze of lemon until "
               "it tastes balanced rather than just hot.",
    ),

    "indian": dict(
        label="Indian",
        templates=("curry", "soup", "traybake", "pilaf", "bake", "stew",
                   "skillet"),
        bases=("White basmati rice, dry", "Dried red lentils", "Brown rice, dry",
               "Sweet potato, raw", "Potato, raw", "Bulgur wheat, dry"),
        veg=("Cauliflower, raw", "Baby spinach", "Carrot, raw", "Eggplant, raw",
             "Green beans, frozen", "Capsicum, raw", "Peas, frozen",
             "Tomato, raw", "Brown onion, raw", "Pumpkin, raw"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Lamb leg, raw, diced", "Lamb mince, raw", "Firm tofu",
                  "Chickpeas, drained", "Brown lentils, drained",
                  "Red kidney beans, drained", "Prawns, raw, peeled",
                  "White fish fillet, raw", "Eggs"),
        aromatics={"Garam masala": 6, "Ground cumin": 4, "Fresh ginger": 8,
                   "Garlic": 6, "Light coconut milk": 70},
        dishes={"curry": "{protein} curry with {base}",
                "pilaf": "{protein} biryani with {veg}",
                "soup": "{protein} and {veg} dal with {base}",
                "traybake": "Tandoori-style {protein} with {base} and {veg}",
                "stew": "{protein} and {veg} masala with {base}",
                "skillet": "{protein} bhuna with {veg} and {base}"},
        finish="Fry the spices in the oil for a minute before anything else "
               "goes in -- raw garam masala tastes dusty.",
    ),

    "greek": dict(
        label="Greek",
        templates=("traybake", "bowl", "soup", "salad", "grill", "bake",
                   "braise", "skillet"),
        bases=("Potato, raw", "Couscous, dry", "White basmati rice, dry",
               "Bulgur wheat, dry", "Quinoa, dry", "Wholemeal pasta, dry"),
        veg=("Zucchini, raw", "Capsicum, raw", "Cherry tomatoes",
             "Eggplant, raw", "Baby spinach", "Cucumber, raw",
             "Brown onion, raw", "Tomato, raw", "Green beans, frozen",
             "Silverbeet, raw"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Lamb leg, raw, diced", "Lamb mince, raw", "Haloumi",
                  "White fish fillet, raw", "Prawns, raw, peeled",
                  "Chickpeas, drained", "Butter beans, drained", "Eggs"),
        aromatics={"Lemon": 25, "Dried oregano": 2, "Garlic": 6,
                   "Feta cheese": 30, "Extra virgin olive oil": 10},
        dishes={"grill": "{protein} souvlaki with {base} and {veg}",
                "bake": "{protein} and {veg} bake with {base}",
                "braise": "{protein} stifado with {veg} and {base}",
                "traybake": "{protein} and {veg} in the oven with {base}",
                "soup": "{protein} and {veg} avgolemono with {base}",
                "skillet": "{protein} and {veg} briam with {base}"},
        finish="Crumble the feta over after cooking, and be generous with the "
               "lemon -- it is what makes it taste Greek rather than plain.",
    ),

    "mexican": dict(
        label="Mexican",
        templates=("bowl", "ragu", "traybake", "wrap", "salad", "skillet",
                   "stew", "bake"),
        bases=("Corn tortillas", "White basmati rice, dry", "Brown rice, dry",
               "Wholemeal wraps", "Sweet potato, raw", "Quinoa, dry"),
        veg=("Capsicum, raw", "Cherry tomatoes", "Zucchini, raw",
             "Carrot, raw", "Baby spinach", "Corn kernels",
             "Brown onion, raw", "Tomato, raw", "Cabbage, raw",
             "Cauliflower, raw"),
        proteins=("Beef mince, lean, raw", "Chicken breast, raw",
                  "Chicken thigh fillet, raw, skinless", "Pork mince, raw",
                  "Turkey mince, lean, raw", "Black beans, drained",
                  "Red kidney beans, drained", "Prawns, raw, peeled",
                  "White fish fillet, raw", "Eggs"),
        aromatics={"Ground cumin": 4, "Smoked paprika": 4, "Garlic": 6,
                   "Lemon": 25, "Extra virgin olive oil": 10},
        dishes={"wrap": "{protein} burritos with {veg}",
                "bowl": "{protein} burrito bowl with {veg}",
                "ragu": "{protein} chilli with {base}",
                "stew": "{protein} and {veg} chilli with {base}",
                "skillet": "{protein} fajita skillet with {veg} and {base}",
                "traybake": "{protein} and {veg} sheet-pan tacos with {base}",
                "bake": "{protein} and {veg} enchilada bake with {base}"},
        finish="Squeeze lemon over at the table. Warm the tortillas in a dry "
               "pan for twenty seconds a side.",
    ),

    "irish": dict(
        label="Irish",
        templates=("soup", "traybake", "stew", "braise", "chowder", "bake",
                   "skillet"),
        bases=("Potato, raw", "Sweet potato, raw", "Pearl barley, dry"),
        veg=("Carrot, raw", "Leek, raw", "Cabbage, raw", "Mushrooms, raw",
             "Green beans, frozen", "Celery, raw", "Brown onion, raw",
             "Peas, frozen", "Kale, raw", "Brussels sprouts, raw"),
        proteins=("Beef chuck, raw, diced", "Lamb leg, raw, diced",
                  "Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "White fish fillet, raw", "Pork loin, raw",
                  "Butter beans, drained", "Brown lentils, drained",
                  "Beef mince, lean, raw", "Lamb mince, raw"),
        aromatics={"Beef stock cubes": 5, "Butter": 10, "Garlic": 6},
        dishes={"stew": "{protein} and {veg} stew with {base}",
                "chowder": "{protein} chowder with {base}",
                "bake": "{protein} and {veg} cottage bake with {base}",
                "soup": "{protein} and {veg} broth with {base}",
                "braise": "{protein} braised in stout with {veg} and {base}",
                "skillet": "{protein} and {veg} hash with {base}"},
        finish="Let it sit twenty minutes off the heat before serving; a stew "
               "is always better slightly rested.",
    ),

    "middle-eastern": dict(
        label="Middle Eastern",
        templates=("traybake", "bowl", "soup", "tagine", "salad", "grill",
                   "pilaf", "wrap", "stew"),
        bases=("Couscous, dry", "Dried red lentils", "White basmati rice, dry",
               "Bulgur wheat, dry", "Quinoa, dry", "Wholemeal wraps",
               "Sweet potato, raw"),
        veg=("Eggplant, raw", "Capsicum, raw", "Zucchini, raw",
             "Cherry tomatoes", "Carrot, raw", "Baby spinach",
             "Cauliflower, raw", "Cucumber, raw", "Brown onion, raw",
             "Pumpkin, raw"),
        proteins=("Chicken breast, raw", "Chicken thigh fillet, raw, skinless",
                  "Lamb leg, raw, diced", "Lamb mince, raw",
                  "Chickpeas, drained", "Brown lentils, drained",
                  "Butter beans, drained", "Haloumi", "White fish fillet, raw",
                  "Beef chuck, raw, diced"),
        aromatics={"Ground cumin": 4, "Tahini": 20, "Lemon": 25, "Garlic": 6,
                   "Extra virgin olive oil": 10},
        dishes={"tagine": "{protein} tagine with {veg} and {base}",
                "salad": "{protein} and {base} tabbouleh with {veg}",
                "grill": "{protein} kofta skewers with {base} and {veg}",
                "wrap": "{protein} and {veg} in flatbread",
                "soup": "{protein} and {veg} harira with {base}",
                "stew": "{protein} and {veg} stew with {base}",
                "traybake": "{protein} and {veg} sheet bake with {base}"},
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


# A meal-prep week is not seven independent dishes -- it is a handful of
# things bought and cooked once, plated a different way each day. Roasting
# one tray of chicken breast that turns up in Monday's bowl and Wednesday's
# stir-fry is one thing to buy, one thing to cook and one thing to wash up;
# picking a fresh protein for every dish is five of each for a week that eats
# the same way.
#
# Two roles are worth locking to a shared pool: protein, because it is what
# dominates both the shopping cost and the pan on Sunday, and base, because a
# rice cooker or a pot of pasta is exactly the kind of thing worth running
# once for the whole week rather than once per dish. Veg is left free --
# reusing the exact same vegetable in every dish is not variety, and a bag of
# frozen mixed veg covers most of it in one step regardless of which dish it
# lands in.
_POOL_CAP = 2
_POOL_ROLES = ("protein", "base")


def _template_reuses_pool(template_id: str, pool: Optional[Dict[str, List[str]]],
                          cuisine: str, diet: Optional[str],
                          exclude: Sequence[str]) -> bool:
    """Could this template actually be built from something the pool holds?"""
    if not pool:
        return False
    for role in _POOL_ROLES:
        have = pool.get(role) or []
        if not have:
            continue
        options, _ = _pool_for(role, cuisine, diet, exclude, template_id)
        if any(food in options for food in have):
            return True
    return False


def _pick_preferred(role: str, pool: Dict[str, List[str]], cuisine: str,
                    diet: Optional[str], exclude: Sequence[str],
                    template_id: Optional[str], seed: str, offset: int
                    ) -> Optional[str]:
    """Reuse whatever this role is already using elsewhere this week.

    Falls back to the ordinary seeded pick when nothing already chosen fits
    this template, diet or cuisine -- a Mexican dinner does not get stuck with
    Tuesday's soy-glazed chicken just because it came first.
    """
    options, _ = _pool_for(role, cuisine, diet, exclude, template_id)
    if not options:
        return None
    have = pool.get(role) or []
    compatible = [food for food in have if food in options]
    if compatible:
        return _pick(compatible, seed, offset)
    choice = _pick(options, seed, offset)
    if choice and len(have) < _POOL_CAP:
        pool.setdefault(role, [])
        if choice not in pool[role]:
            pool[role].append(choice)
    return choice


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
    fibre_target: Optional[float] = None,
) -> Dict[str, float]:
    """Scale to the targets: protein sets the meat, the base fills the energy.

    A fibre floor is met the only way it honestly can be, by serving more
    vegetables. Solving once at the standard portion says how far short it
    falls, and the second pass buys that gap in whatever vegetable is in the
    dish -- so asking for 30g of fibre a day produces a bigger plate rather
    than the same plate with a note saying it missed.
    """
    solved = _solve_once(protein, base, veg, extras, kcal_target,
                         protein_target, _VEG_PER_SERVE)
    if not fibre_target:
        return solved

    fb_per_100 = INGREDIENTS[veg]["fb"] or 0.0
    have = sum(INGREDIENTS[n]["fb"] * g / 100.0
               for n, g in solved.items() if n in INGREDIENTS)
    short = fibre_target - have
    if short <= 0 or fb_per_100 <= 0:
        return solved

    veg_g = min(_VEG_PER_SERVE + short / fb_per_100 * 100.0, _VEG_CEILING)
    return _solve_once(protein, base, veg, extras, kcal_target,
                       protein_target, veg_g)


def _solve_once(
    protein: str, base: str, veg: str, extras: Dict[str, float],
    kcal_target: float, protein_target: float, veg_g: float,
) -> Dict[str, float]:
    fixed = dict(extras)
    fixed[veg] = veg_g

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
    pick: Optional[Dict[str, str]] = None,
    fibre_per_serving: Optional[float] = None,
    meal: Optional[str] = None,
    prefer_pool: Optional[Dict[str, List[str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Compose one recipe meeting the targets, or None if nothing fits.

    `pick` names the protein, base and vegetable outright instead of letting
    the seed choose them. That is what makes the book browsable: every
    combination can be asked for by name and comes back the same every time,
    rather than being whatever a hash happened to land on.

    `prefer_pool`, if given, is read *and written*: a dish generated with it
    reuses whichever protein and base are already in the pool when they fit,
    and adds its own choice to the pool otherwise (up to a small cap). Callers
    building several dishes for one week share the same dict across every call
    so a roast chicken and a pot of rice keep turning up rather than a fresh
    protein and starch for every single one.
    """
    theme = CUISINES.get(cuisine or "any") or CUISINES["any"]
    allowed = theme.get("templates") or ()
    for_meal = set(templates_for_meal(meal))

    templates = [t for t in TEMPLATES
                 if (not template_id or t["id"] == template_id)
                 and (not allowed or t["id"] in allowed)
                 and t["id"] in for_meal]
    if not templates and meal and meal != "any":
        # No theme lists a breakfast, and nor should they -- porridge is not
        # Greek. Rather than refuse the meal, drop the theme for it and say so
        # by not claiming the label.
        theme = CUISINES["any"]
        cuisine = "any"
        templates = [t for t in TEMPLATES
                     if (not template_id or t["id"] == template_id)
                     and t["id"] in for_meal]
    if not templates:
        return None

    # Walk the allowed templates from a seeded start, keeping the first that
    # the theme can actually fill. Two passes when there is a pool to reuse:
    # first only templates that could actually carry the protein or base
    # already committed to elsewhere this week, then the ordinary walk,
    # unchanged, if none of them can. Without a pass biased toward reuse, the
    # pool only ever helps by coincidence -- the template gets picked first,
    # independently of what is already in the pool, and most of the time
    # nothing in the pool happens to suit whatever template that was.
    start = int(hashlib.sha256(f"{seed}:t:{offset}".encode()).hexdigest()[:8], 16)
    template = templates[start % len(templates)]
    off_theme_roles: List[str] = []
    found_template = False
    for prefer_only in ((True, False) if prefer_pool else (False,)):
        for step in range(len(templates)):
            candidate = templates[(start + step) % len(templates)]
            tid = candidate["id"]
            if prefer_only and not _template_reuses_pool(
                    tid, prefer_pool, cuisine, diet, exclude):
                continue
            misses = [role for role in ("protein", "base", "veg")
                      if not _pool_for(role, cuisine, diet, exclude, tid)[1]]
            if not misses:
                template = candidate
                off_theme_roles = []
                found_template = True
                break
            if step == 0 and not prefer_only:
                off_theme_roles = misses
        if found_template:
            break
    

    tid = template["id"]
    chosen = pick or {}
    if prefer_pool is not None:
        protein = chosen.get("protein") or _pick_preferred(
            "protein", prefer_pool, cuisine, diet, exclude, tid, seed, offset * 7 + 1)
        base = chosen.get("base") or _pick_preferred(
            "base", prefer_pool, cuisine, diet, exclude, tid, seed, offset * 7 + 2)
    else:
        protein = chosen.get("protein") or _pick(
            _pool_for("protein", cuisine, diet, exclude, tid)[0], seed, offset * 7 + 1)
        base = chosen.get("base") or _pick(
            _pool_for("base", cuisine, diet, exclude, tid)[0], seed, offset * 7 + 2)
    veg_pool = _pool_for("veg", cuisine, diet, exclude, tid)[0]
    if fibre_per_serving and not chosen.get("veg"):
        # Some vegetables cannot carry a fibre floor at any sane portion: a
        # tomato is 1.2g per 100, so four hundred grams of it still leaves the
        # day short while crowding out everything else on the plate. Ask the
        # ones that can, and only fall back if the theme has none.
        able = [name for name in veg_pool
                if INGREDIENTS[name]["fb"] * _VEG_CEILING / 100.0
                >= fibre_per_serving * 0.6]
        veg_pool = able or veg_pool
    veg = chosen.get("veg") or _pick(veg_pool, seed, offset * 7 + 3)
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
            if diet == "keto" and "keto" not in tags:
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
        protein, base, veg, extras, kcal_per_serving, protein_per_serving,
        fibre_per_serving)
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
    # A theme names its own dishes. "Japanese-style chicken donburi" says more
    # than "Japanese-style chicken and rice bowl", and it is the same dish.
    pattern = (theme.get("dishes") or {}).get(template["id"]) or template["name"]
    # A pattern that does not mention every role produces the same title for
    # genuinely different dishes -- every donburi reads "chicken donburi with
    # bok choy" whether it is on jasmine or brown rice. Name what was left out
    # rather than show two tiles a reader cannot tell apart.
    if "{veg}" not in pattern:
        pattern += " and {veg}"
    if "{base}" not in pattern:
        pattern += " on {base}"
    if "{protein}" not in pattern:
        pattern += " and {protein}"
    title = pattern.format(**labels)
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
                # So a shopping list can say how much to buy rather than how
                # many packs of something that does not come in packs.
                "loose": bool(INGREDIENTS[name].get("loose")),
            }
            for name, grams in sorted(
                per_serve.items(), key=lambda kv: -kv[1])
        ],
        "meal": (meals_for(template["id"])[0]
                 if meal in (None, "any") else meal),
        "meals": list(meals_for(template["id"])),
        "cuisine": cuisine if cuisine in CUISINES else "any",
        "cuisineLabel": theme.get("label", ""),
        "steps": ([s.format(**labels) for s in template["steps"]]
                  + ([theme["finish"]] if theme.get("finish") else [])),
        "storage": template.get("storage", ""),
        "protein": protein,
        "base": base,
        "veg": veg,
        "reheat": list(template.get("reheat", ())),
        # What a Sunday cook sheet schedules against: what has to be free to
        # cook this (an oven and a stovetop each host one dish at a time),
        # and how many minutes are hands-on versus just sitting there.
        "device": template.get("device", "stovetop"),
        "activeMinutes": template.get("active_min", 10),
        "passiveMinutes": template.get("passive_min", 0),
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

# How a day's energy actually falls across its meals. Splitting a day evenly is
# the arithmetic answer and not how anyone eats: breakfast is smaller than
# dinner in every country that has all three. Building every meal to the same
# 600 kcal produces a plan of interchangeable lunches.
#
# An even split is still offered, because somebody batch-cooking one dish to
# eat three times a day genuinely does want three identical portions. That is a
# real way to eat and the choice belongs to the person, not to this table.
MEAL_SHARE: Dict[str, float] = {
    "breakfast": 0.25,
    "lunch": 0.35,
    "dinner": 0.40,
}


def share_for(meal: Optional[str], meals_per_day: int = 3,
              even: bool = False) -> float:
    """What fraction of the day this sitting is worth."""
    if even or not meal or meal not in MEAL_SHARE:
        return 1.0 / max(1, meals_per_day)
    if meals_per_day == 3:
        return MEAL_SHARE[meal]
    # Away from three meals the named shares stop adding up, so they are
    # rescaled rather than quietly over- or under-feeding the day.
    total = sum(MEAL_SHARE.values())
    return MEAL_SHARE[meal] / total


# Targets for a day, by what somebody is trying to do. The protein figures are
# grams per kilogram of bodyweight, which is how the research and every coach
# states them; the app multiplies by the weight you give it.
#
# These are ordinary published ranges, not advice, and the page says so.
PROFILES: Dict[str, Dict[str, Any]] = {
    "lean": dict(
        label="Losing fat",
        kcalPerKg=26.0, proteinPerKg=2.2, fibrePer1000kcal=14.0,
        note="A deficit with protein kept high, which is what protects muscle "
             "while the weight comes off.",
    ),
    "maintain": dict(
        label="Staying put",
        kcalPerKg=33.0, proteinPerKg=1.8, fibrePer1000kcal=14.0,
        note="Roughly what an averagely active person burns.",
    ),
    "build": dict(
        label="Building muscle",
        kcalPerKg=38.0, proteinPerKg=2.0, fibrePer1000kcal=12.0,
        note="A modest surplus. Much more than this is mostly fat, whatever "
             "the internet says.",
    ),
    "endurance": dict(
        label="Training hard",
        kcalPerKg=42.0, proteinPerKg=1.7, fibrePer1000kcal=12.0,
        note="More carbohydrate to train on, protein still comfortably above "
             "the minimum.",
    ),
}


def targets_for(profile: str, weight_kg: float) -> Dict[str, float]:
    """A day's numbers for a profile and a bodyweight."""
    meta = PROFILES.get(profile) or PROFILES["maintain"]
    weight = max(30.0, min(float(weight_kg or 80.0), 250.0))
    kcal = round(meta["kcalPerKg"] * weight / 50) * 50
    return {
        "ceiling": float(kcal),
        "floorP": float(round(meta["proteinPerKg"] * weight / 5) * 5),
        "floorF": float(round(meta["fibrePer1000kcal"] * kcal / 1000)),
    }


def profile_names() -> List[Dict[str, str]]:
    return [{"id": key, "label": meta["label"], "note": meta["note"]}
            for key, meta in PROFILES.items()]


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
            "fatMax": 0.9, "fibreMin": 1.4}


def serving_cost(recipe: Dict[str, Any],
                 prices: Optional[Dict[str, Dict[str, Any]]]) -> Optional[float]:
    """What one serving's ingredients cost, at the per-kilo rate.

    Not what the shopping costs -- that is packs, and the planner works that
    out. This is the fair way to compare two recipes: a dish built on tuna
    steak at $27/kg and one built on kidney beans at $5/kg are not equivalent
    just because they carry the same protein.
    """
    if not prices:
        return None
    total = 0.0
    known = 0
    for part in recipe.get("ingredients", []):
        price = prices.get(part.get("food"))
        grams = float(part.get("gramsPerServing") or 0)
        if not price or grams <= 0:
            continue
        per_kg = price.get("perKg")
        if not per_kg and price.get("price") and price.get("pack"):
            per_kg = price["price"] * 1000.0 / price["pack"]
        if not per_kg:
            continue
        total += per_kg * grams / 1000.0
        known += 1
    return round(total, 2) if known else None


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
    meal: Optional[str] = None,
    prices: Optional[Dict[str, Dict[str, Any]]] = None,
    cost_ceiling: Optional[float] = None,
    prefer_pool: Optional[Dict[str, List[str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Build several candidates and return the one that best fits the targets.

    With prices, "best" includes what it costs. A week of forty grams of
    protein a meal can be built on tuna steak or on chicken and kidney beans,
    and the difference across twenty-one meals is several hundred dollars --
    which the old scoring could not see at all, because it only ever looked at
    the macros.
    """
    t = {**DEFAULT_TARGETS, **(targets or {})}
    if diet == "keto" and t.get("carbMax") is None:
        t["carbMax"] = KETO_CARBS_PER_SERVING
    best = None
    best_score = None
    for step in range(max(1, tries)):
        candidate = _finish(build_recipe(
            seed, servings, t["kcal"], t["protein"], diet, exclude,
            offset=start_offset + step, cuisine=cuisine,
            fibre_per_serving=t.get("fibreMin"), meal=meal,
            prefer_pool=prefer_pool))
        if candidate is None:
            continue
        penalty = score_against(candidate["perServing"], t)
        cost = serving_cost(candidate, prices)
        if cost is not None:
            candidate["servingCost"] = cost
            if cost_ceiling:
                # What counts is not what a serving costs but what its protein
                # costs. Penalising the plain price pushed the builder onto
                # beans and grains -- cheap, and nowhere near 150g a day. A
                # $4 serving carrying 55g of protein is better value than a $2
                # one carrying 20g, and that is the choice the old plan made
                # over and over: whey, yoghurt, chicken breast, lean mince.
                protein = max(1.0, candidate["perServing"].get("p") or 0.0)
                rate = cost / protein
                candidate["costPerProtein"] = round(rate, 4)
                over = max(0.0, rate - cost_ceiling) / cost_ceiling
                penalty += 1.6 * over + 0.3 * (rate / cost_ceiling)
        if prefer_pool:
            # `build_recipe` already prefers reusing the pool when a template
            # allows it, but this loop tries several templates and keeps
            # whichever scores best on macros and cost alone -- with nothing
            # here, a candidate that happened not to reuse anything can still
            # win by a fraction of a point, and the whole point of the pool
            # was to make reuse the thing actually chosen, not just attempted.
            if candidate.get("protein") in (prefer_pool.get("protein") or []):
                penalty -= 0.12
            if candidate.get("base") in (prefer_pool.get("base") or []):
                penalty -= 0.06
        if prices:
            # "Buy the fish on price, not on the plan" -- build to what is
            # actually discounted this week rather than to a fixed favourite,
            # the same reasoning the reference plan's swap table argued for.
            # A small nudge, not a rule: it only breaks a near-tie, the way
            # the pool bonus above does.
            if (prices.get(candidate.get("protein")) or {}).get("onSpecial"):
                penalty -= 0.10
            if (prices.get(candidate.get("base")) or {}).get("onSpecial"):
                penalty -= 0.05
        if best_score is None or penalty < best_score:
            best, best_score = candidate, penalty
        if penalty < 0.05 and not cost_ceiling:
            break               # close enough; stop burning effort
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
    meals_wanted: Optional[Sequence[str]] = None,
    prices: Optional[Dict[str, Dict[str, Any]]] = None,
    cost_ceiling: Optional[float] = None,
    prefer_pool: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Build several distinct recipes for one week's prep.

    `meals_wanted` spreads them over the day -- ask for nine with breakfast,
    lunch and dinner and you get three of each, rather than nine dinners and a
    week that suggests chicken ragu at seven in the morning.

    Every dish generated in this call shares one pool of proteins and bases,
    so the second and third dishes reuse what the first one already committed
    to rather than rolling something new. Pass a dict in from outside (and
    reuse the same dict across several calls) to share that pool across a
    whole week rather than just one batch -- a roast chicken bought for
    lunch is a roast chicken dinner can reuse too.
    """
    goals = {**DEFAULT_TARGETS, "kcal": kcal_per_serving,
             "protein": protein_per_serving, **(targets or {})}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    pool: Dict[str, List[str]] = prefer_pool if prefer_pool is not None else {}

    # Round-robin over the meals asked for, so nine dishes across three meals
    # come back three, three and three rather than however the seed fell.
    wanted = list(meals_wanted or [None])
    quotas = [meals // len(wanted) + (1 if i < meals % len(wanted) else 0)
              for i in range(len(wanted))]

    for meal, quota in zip(wanted, quotas):
        offset = 0
        made = 0
        # Try well past the quota so exclusions cannot silently return short.
        while made < quota and offset < max(8, quota * 8):
            recipe = build_best(seed, goals, servings, diet, exclude, cuisine,
                                tries=8 if prices else 4, start_offset=offset,
                                meal=meal, prices=prices,
                                cost_ceiling=cost_ceiling, prefer_pool=pool)
            offset += 4
            if not recipe:
                continue
            key = (recipe["template"], recipe["ingredients"][0]["food"])
            if key in seen:
                continue
            seen.add(key)
            recipe["id"] = f"{recipe['template']}-{len(out) + 1}"
            out.append(recipe)
            made += 1
    return out


def combinations(cuisine: str = "any", diet: Optional[str] = None,
                 exclude: Sequence[str] = (),
                 meal: Optional[str] = None) -> List[Dict[str, str]]:
    """Every dish this theme can make, in a stable but well-shuffled order.

    Enumerated in template order the list reads as twenty chicken tray bakes
    followed by twenty beef ones, which looks like far less variety than there
    is. Sorting by a hash of the combination fixes that without making the
    order random: the same request always returns the same page, so paging
    through the book never shows a dish twice or skips one.
    """
    theme = CUISINES.get(cuisine or "any") or CUISINES["any"]
    allowed = theme.get("templates") or ()
    for_meal = set(templates_for_meal(meal))
    # A theme has no breakfasts, so asking for one is asking for it untethered
    # from the theme rather than for nothing at all.
    if allowed and not (set(allowed) & for_meal):
        allowed = ()
    out: List[Dict[str, str]] = []
    for template in TEMPLATES:
        tid = template["id"]
        if tid not in for_meal:
            continue
        if allowed and tid not in allowed:
            continue
        proteins = _pool_for("protein", cuisine, diet, exclude, tid)[0]
        bases = _pool_for("base", cuisine, diet, exclude, tid)[0]
        vegs = _pool_for("veg", cuisine, diet, exclude, tid)[0]
        for protein in proteins:
            for base in bases:
                for veg in vegs:
                    out.append({"template": tid, "protein": protein,
                                "base": base, "veg": veg})
    # Sorting the whole list by a hash spreads the proteins nicely but not the
    # shapes: a frittata has ninety-six combinations and a porridge six, so the
    # opening page of breakfasts was six frittatas. Shuffle within each shape,
    # then deal them out one shape at a time, so the first page shows what
    # there is rather than whatever is most numerous.
    by_shape: Dict[str, List[Dict[str, str]]] = {}
    for combo in out:
        by_shape.setdefault(combo["template"], []).append(combo)
    for combos in by_shape.values():
        combos.sort(key=lambda c: hashlib.sha256(
            f"{c['template']}|{c['protein']}|{c['base']}|{c['veg']}".encode()
        ).hexdigest())

    dealt: List[Dict[str, str]] = []
    shapes = sorted(by_shape)
    round_no = 0
    while len(dealt) < len(out):
        for shape in shapes:
            combos = by_shape[shape]
            if round_no < len(combos):
                dealt.append(combos[round_no])
        round_no += 1
    return dealt


def browse(
    cuisine: str = "any",
    diet: str = "any",
    exclude: Sequence[str] = (),
    category: Optional[str] = None,
    servings: int = 4,
    kcal_per_serving: float = 600,
    protein_per_serving: float = 40,
    limit: int = 60,
    offset: int = 0,
    meal: Optional[str] = None,
) -> Dict[str, Any]:
    """A page of the book, and how big the book is."""
    combos = combinations(cuisine, diet if diet != "any" else None, exclude, meal)
    total = len(combos)

    recipes: List[Dict[str, Any]] = []
    index = max(0, offset)
    # Walk past anything the filters reject rather than returning a short page
    # with gaps in it, but stop walking eventually -- a category with nothing
    # in it should return empty, not read the whole book looking.
    while len(recipes) < limit and index < total and index < offset + limit * 20:
        combo = combos[index]
        index += 1
        recipe = _finish(build_recipe(
            seed=f"{cuisine}:{index}", servings=servings,
            kcal_per_serving=kcal_per_serving,
            protein_per_serving=protein_per_serving, diet=diet,
            exclude=exclude, template_id=combo["template"], cuisine=cuisine,
            pick=combo, meal=meal))
        if recipe is None:
            continue
        if category and recipe.get("category") != category:
            continue
        if diet == "keto" and net_carbs(
                recipe["perServing"]) > KETO_CARBS_PER_SERVING:
            continue        # every part inside the limit, the plateful not
        recipe["id"] = (f"{cuisine}:{combo['template']}:{combo['protein']}"
                        f":{combo['base']}:{combo['veg']}")
        recipes.append(recipe)

    return {"cuisine": cuisine, "meal": meal or "any", "total": total,
            "offset": offset,
            "nextOffset": index if index < total else None,
            "count": len(recipes), "recipes": recipes}


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
