"""Swapping the product behind a shopping line, and it staying swapped."""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace(chr(92), "/")
os.environ["SESSION_SECRET"] = "t"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SIGNUP_MODE"] = "open"
sys.path.insert(0, os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server"))

from fastapi.testclient import TestClient  # noqa: E402
from webapp import pricing  # noqa: E402
from webapp.db import SessionLocal, Product  # noqa: E402
from webapp.app import app  # noqa: E402

fails = []


def check(label, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


# The tables have to exist before anything is put in them; the app creates
# them on startup, which has not happened yet at module level.
from webapp.db import init_db  # noqa: E402

init_db()

# Two products for the same food: one the resolver prefers, one you might.
with SessionLocal() as session:
    pricing.remember_products(session, "woolworths", [
        {"name": "Woolworths Chicken Breast Fillet 1kg", "stockcode": "111",
         "pack_price": 12.0, "pack_g": 1000, "per_kg": 12.0, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "1kg", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": ""},
        {"name": "Macro Organic Chicken Breast Fillet 500g", "stockcode": "222",
         "pack_price": 15.0, "pack_g": 500, "per_kg": 30.0, "in_stock": True,
         "barcode": "", "brand": "", "package_size": "500g", "cup_string": "",
         "on_special": True, "was_price": 18.0, "url": "", "image": ""},
    ])

with TestClient(app) as c:
    c.post("/api/auth/register",
           json={"email": "s@example.com", "password": "a-long-enough-password"})
    pid = c.post("/api/plans", json={"name": "T", "data": {}}).json()["id"]

    r = c.get("/api/alternatives",
              params={"food": "Chicken breast, raw", "query": "chicken breast",
                      "pack": 1000}).json()
    check("alternatives come back", r["count"] >= 2, str(r["count"]))
    names = [p["name"] for p in r["products"]]
    check("both products are offered", len(names) == len(set(names)) >= 2)
    check("each carries a price and a pack",
          all(p.get("pack_price") and p.get("pack_g") for p in r["products"]))
    check("and how well it matches",
          all("match" in p for p in r["products"]))

    # Pin the dearer organic one, as somebody might.
    data = c.get(f"/api/plans/{pid}").json()["data"]
    data["shop"] = {"Chicken breast, raw": {
        "aisle": "meat", "grams": 1000, "pack": 500, "packsNeeded": 2,
        "woo": "chicken breast", "stockcode": "222",
        "pinned": "Macro Organic Chicken Breast Fillet 500g"}}
    data["prices"] = {}
    c.put(f"/api/plans/{pid}", json={"data": data})

    r = c.post(f"/api/plans/{pid}/refresh-prices", json={"stores": ["woolworths"]})
    check("a refresh succeeds", r.status_code == 200, r.text[:70])

    after = c.get(f"/api/plans/{pid}").json()["data"]
    latest = (after["prices"].get("Chicken breast, raw") or [{}])[-1]
    check("the chosen product survives the refresh",
          latest.get("matched") == "Macro Organic Chicken Breast Fillet 500g",
          str(latest.get("matched")))
    check("priced as that product", latest.get("price") == 15.0,
          str(latest.get("price")))
    check("and its special is carried through",
          latest.get("onSpecial") is True and latest.get("wasPrice") == 18.0,
          str({k: latest.get(k) for k in ("onSpecial", "wasPrice")}))

    # A line nobody pinned should still be re-resolved normally.
    data = c.get(f"/api/plans/{pid}").json()["data"]
    data["shop"]["Chicken breast, raw"].pop("pinned")
    c.put(f"/api/plans/{pid}", json={"data": data})
    c.post(f"/api/plans/{pid}/refresh-prices", json={"stores": ["woolworths"]})
    after = c.get(f"/api/plans/{pid}").json()["data"]
    latest = (after["prices"].get("Chicken breast, raw") or [{}])[-1]
    check("an unpinned line goes back to being matched",
          latest.get("source") != "chosen by hand", str(latest.get("source")))

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
