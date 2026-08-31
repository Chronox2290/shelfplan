"""What the code review turned up, kept so it cannot come back."""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace(chr(92), "/")
os.environ["SESSION_SECRET"] = "t"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SIGNUP_MODE"] = "open"
ROOT = os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server")
sys.path.insert(0, ROOT)

import io  # noqa: E402

from webapp import autoprice, pricing  # noqa: E402
from webapp.db import SessionLocal, init_db  # noqa: E402
from src.supermarkets import catalog, resolve  # noqa: E402

fails = []


def check(label, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


app_js = io.open(os.path.join(ROOT, "webapp", "static", "app.js"),
                 encoding="utf-8").read()

print("no source file hides a stray control byte where an escape belongs")
# The exact bug this catches: a regex word-boundary escape got collapsed by
# some intermediate tool into the single control byte a couple of escape
# dialects give that same two-character spelling, leaving a regex that still
# parses and still runs, just against a control byte that real text never
# contains -- so it silently stops matching anything. It happened twice in
# one session, in two different languages, and a syntax check caught neither
# time, because the file was still syntactically valid. Nothing legitimate in
# this project's source ever needs a literal control byte below the space
# character other than tab, newline and carriage return.
_control_names = {chr(0): "NUL", chr(1): "SOH", chr(8): "backspace",
                  chr(11): "vertical tab", chr(12): "form feed"}
for relative in ("webapp/static/app.js", "webapp/static/index.html", "webapp/app.py",
                 "webapp/pricing.py", "src/supermarkets/recipes.py",
                 "src/supermarkets/weekplan.py", "src/supermarkets/recipe_import.py",
                 "src/supermarkets/resolve.py", "src/supermarkets/catalog.py"):
    text = io.open(os.path.join(ROOT, *relative.split("/")), encoding="utf-8").read()
    found = [name for ch, name in _control_names.items() if ch in text]
    check(f"{relative} has no stray control bytes", not found, str(found))

print("a reset link has to reach the reset screen")
boot = app_js[app_js.index("async function boot()"):]
boot = boot[:boot.index("\n}\n")]
check("boot checks for a reset token", "pendingResetToken()" in boot)
check("and shows the reset screen", "showReset()" in boot)
check("before asking who is signed in",
      boot.index("pendingResetToken()") < boot.index("/auth/me"))

print("pictures are not deferred into oblivion")
check("nothing is lazily loaded", 'loading="lazy"' not in app_js)

print("one lookup, not four that drift apart")
for module in ("app.py", "autoprice.py"):
    text = io.open(os.path.join(ROOT, "webapp", module), encoding="utf-8").read()
    strays = re.findall(r"pricing\.catalogue_search\(\s*\n?\s*session,\s*query=", text)
    # app.py keeps exactly one: the catalogue search box, where a query is a
    # query and narrowing it is the point.
    allowed = 1 if module == "app.py" else 0
    check(f"{module} does its ingredient lookups through candidates_for",
          len(strays) <= allowed, f"{len(strays)} direct calls")

print("the shared lookup does what each caller used to do separately")
init_db()
with SessionLocal() as session:
    pricing.remember_products(session, "woolworths", [
        {"name": "La Gina Polenta Corn Meal 500g", "stockcode": "1",
         "pack_price": 3.0, "pack_g": 500, "per_kg": 6.0, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "500g", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": "",
         "department": "GROCERIES"},
        {"name": "Marco Polo Polenta 750g", "stockcode": "2",
         "pack_price": 3.2, "pack_g": 750, "per_kg": 4.3, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "750g", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": "",
         "department": "GROCERIES"},
        {"name": "Mutti Whole Cherry Tomatoes 400g", "stockcode": "3",
         "pack_price": 1.85, "pack_g": 400, "per_kg": 4.6, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "400g", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": "",
         "department": "GROCERIES"},
        {"name": "Woolworths Cherry Tomatoes Punnet 250g", "stockcode": "4",
         "pack_price": 3.2, "pack_g": 250, "per_kg": 12.8, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "250g", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": "",
         "department": "FRUIT AND VEG"},
    ])

with SessionLocal() as session:
    got = pricing.candidates_for(session, "Polenta, dry", "Polenta 500g")
    names = [p["name"] for p in got]
    check("a pack size in the query does not hide the other pack",
          any("Marco Polo" in n for n in names), "; ".join(names)[:70])

    got = pricing.candidates_for(
        session, "Cherry tomatoes", "Cherry Tomatoes 250g", aisle="produce")
    names = [p["name"] for p in got]
    check("produce is looked for in the produce aisle",
          names == ["Woolworths Cherry Tomatoes Punnet 250g"], "; ".join(names)[:70])

    got = pricing.candidates_for(session, "Cherry tomatoes", "Cherry Tomatoes 250g")
    check("without an aisle it does not narrow", len(got) >= 2, str(len(got)))

print("a doubtful product and an unweighable one are different")
with SessionLocal() as session:
    pricing.remember_products(session, "woolworths", [
        {"name": "Fresh Broccoli each", "stockcode": "5", "pack_price": 1.49,
         "pack_g": None, "per_kg": None, "in_stock": True, "barcode": "",
         "brand": "", "package_size": "each", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": "",
         "department": "FRUIT AND VEG"},
    ])
with SessionLocal() as session:
    rec = autoprice._price_line(
        session, "Broccoli, raw", {"woo": "Broccoli", "pack": 1000}, [])
    check("something sold by the each still gets priced",
          rec is not None and rec["matched"] == "Fresh Broccoli each",
          str(rec and rec.get("matched")))

    got = pricing.candidates_for(session, "Broccoli, raw", "Broccoli")
    found = resolve.resolve_from_products("Broccoli, raw", "Broccoli", got, 1000)
    check("and is flagged for review without being called a mismatch",
          found.get("needs_review") and not found.get("mismatch"),
          str(found.get("review_reasons")))

# Woolworths sells soft toys, cookbooks and ornaments through the same search
# as its groceries, filed under an "Everyday Market" with no trading
# department. Live search has dropped those for a while; what had not been
# noticed is that rows indexed *before* departments were recorded carry no
# department to judge, so the swap sheet was still offering a "Bananas in
# Pyjamas ... Soft Toy Plush" as a substitute for bananas.
for name, department, edible in [
    ("Bananas in Pyjamas Large Classic Soft Toy Plush 45cm Set of 2", "", False),
    ("Artichoke to Zucchini Cookbook", "", False),
    ("Mushroom Acrylic Ornament", "", False),
    ("Anything at all", "EVERYDAY MARKET", False),
    ("Anything at all", "GENERAL MERCHANDISE", False),
    ("Cavendish Bananas each", "FRUIT AND VEG", True),
    ("Woolworths Broccoli", "", True),
    # Whole words only, or an ingredient disappears for the letters inside it.
    ("Plushenko Greek Yoghurt", "DAIRY", True),
]:
    check(f"{name[:38]!r} is {'food' if edible else 'merchandise'}",
          pricing.is_edible({"name": name, "department": department}) == edible)

# A product with no department at all must record that it came from the
# marketplace, not leave the field blank -- blank is indistinguishable from
# "indexed before we stored departments", and only one of those is safe to bin.
check("a product with no department is marked as marketplace",
      catalog.department_of({}) == catalog.MARKETPLACE,
      catalog.department_of({}))
check("and a real department survives untouched",
      catalog.department_of(
          {"AdditionalAttributes": {"sapdepartmentname": "Fruit and Veg"}})
      == "FRUIT AND VEG")

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
