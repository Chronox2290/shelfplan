"""The weekly price check: schedule, what it writes, and what it leaves alone."""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace(chr(92), "/")
os.environ["SESSION_SECRET"] = "t"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SIGNUP_MODE"] = "open"
sys.path.insert(0, os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server"))

from fastapi.testclient import TestClient  # noqa: E402
from webapp import autoprice, pricing  # noqa: E402
from webapp.db import SessionLocal, init_db  # noqa: E402
from webapp.app import app  # noqa: E402

fails = []


def check(label, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


init_db()
with SessionLocal() as session:
    pricing.remember_products(session, "woolworths", [
        {"name": "Woolworths Broccoli", "stockcode": "1", "pack_price": 4.0,
         "pack_g": 1000, "per_kg": 4.0, "in_stock": True, "barcode": "",
         "brand": "", "package_size": "1kg", "cup_string": "",
         "on_special": True, "was_price": 6.0, "url": "", "image": ""},
        {"name": "Macro Organic Broccoli", "stockcode": "2", "pack_price": 9.0,
         "pack_g": 1000, "per_kg": 9.0, "in_stock": True, "barcode": "",
         "brand": "", "package_size": "1kg", "cup_string": "",
         "on_special": False, "was_price": None, "url": "", "image": ""},
    ])

print("the schedule")
now = datetime(2026, 9, 1, 12, 0)          # a Tuesday lunchtime
hours = autoprice._seconds_until_next_run(now) / 3600
check("Tuesday noon waits for Wednesday morning", 16 < hours < 18,
      f"{hours:.1f}h")
now = datetime(2026, 9, 2, 6, 0)           # Wednesday, just after
hours = autoprice._seconds_until_next_run(now) / 3600
check("just after the hour waits a whole week", 165 < hours < 169,
      f"{hours:.1f}h")
check("it runs on the day the specials change",
      autoprice.status()["day"] == "Wednesday", autoprice.status()["day"])

with TestClient(app) as c:
    c.post("/api/auth/register",
           json={"email": "w@example.com", "password": "a-long-enough-password"})
    pid = c.post("/api/plans", json={"name": "T", "data": {}}).json()["id"]
    data = c.get(f"/api/plans/{pid}").json()["data"]
    old = (date.today() - timedelta(days=30)).isoformat()
    data["shop"] = {
        "Broccoli, raw": {"aisle": "produce", "grams": 1000, "pack": 1000,
                          "woo": "broccoli"},
        "Pinned broccoli": {"aisle": "produce", "grams": 1000, "pack": 1000,
                            "woo": "broccoli", "stockcode": "2",
                            "pinned": "Macro Organic Broccoli"},
    }
    data["prices"] = {"Broccoli, raw": [{"price": 99.0, "pack": 1000,
                                         "date": old, "source": "old"}]}
    c.put(f"/api/plans/{pid}", json={"data": data})

    print("the run")
    done = autoprice.price_everything()
    check("it priced the plan", done["plans"] == 1 and done["lines"] == 2,
          str(done))

    after = c.get(f"/api/plans/{pid}").json()["data"]
    latest = after["prices"]["Broccoli, raw"][-1]
    check("a stale line gets today's price", latest["date"] == date.today().isoformat(),
          latest["date"])
    check("and it is marked as the weekly check",
          latest["source"] == "weekly check", latest["source"])
    check("the old reading is kept, not replaced",
          len(after["prices"]["Broccoli, raw"]) == 2)
    check("a special is recorded as one",
          latest.get("onSpecial") is True and latest.get("wasPrice") == 6.0,
          str({k: latest.get(k) for k in ("onSpecial", "wasPrice")}))

    pinnedLine = after["prices"]["Pinned broccoli"][-1]
    check("a hand-picked product is kept",
          pinnedLine["matched"] == "Macro Organic Broccoli", pinnedLine["matched"])
    check("and priced as that product", pinnedLine["price"] == 9.0,
          str(pinnedLine["price"]))

    print("running it again the same day")
    done = autoprice.price_everything()
    check("nothing is written twice", done["lines"] == 0, str(done))
    again = c.get(f"/api/plans/{pid}").json()["data"]
    check("and the history has not grown",
          len(again["prices"]["Broccoli, raw"]) == 2)

    r = c.get("/api/auto-price")
    check("the status is readable", r.status_code == 200 and r.json()["enabled"],
          r.text[:60])

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
