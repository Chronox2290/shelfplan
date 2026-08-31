"""Deleting a batch of recipes: scoped, exact, and hard to do by accident."""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace(chr(92), "/")
os.environ["SESSION_SECRET"] = "t"
os.environ["COOKIE_SECURE"] = "0"
os.environ["SIGNUP_MODE"] = "open"
sys.path.insert(0, os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server"))

from fastapi.testclient import TestClient  # noqa: E402
from webapp.app import app  # noqa: E402

fails = []


def check(label, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


with TestClient(app) as c:
    c.post("/api/auth/register",
           json={"email": "one@example.com", "password": "a-long-enough-password"})
    pid = c.post("/api/plans", json={"name": "T", "data": {}}).json()["id"]
    c.post(f"/api/plans/{pid}/autoplan",
           json={"days": 7, "meals_per_day": 3, "ceiling": 1900,
                 "floor_protein": 150, "floor_fibre": 25, "apply": True})
    mine = c.get("/api/recipes").json()["recipes"]
    check("a library to delete from", len(mine) >= 6, str(len(mine)))

    c.post("/api/auth/register",
           json={"email": "two@example.com", "password": "a-long-enough-password"})
    c.post("/api/auth/login",
           json={"email": "two@example.com", "password": "a-long-enough-password"})
    r = c.post("/api/recipes/delete-many", json={"ids": [x["id"] for x in mine]})
    check("another account's recipes are untouchable",
          r.status_code == 200 and r.json()["deleted"] == 0, r.text[:60])

    c.post("/api/auth/login",
           json={"email": "one@example.com", "password": "a-long-enough-password"})
    check("and are all still there",
          len(c.get("/api/recipes").json()["recipes"]) == len(mine))

    some = [x["id"] for x in mine[:3]]
    r = c.post("/api/recipes/delete-many", json={"ids": some + [999999]}).json()
    check("deletes exactly the ones named", r["deleted"] == 3 and r["asked"] == 4,
          str(r))
    left = c.get("/api/recipes").json()["recipes"]
    check("and leaves the rest", len(left) == len(mine) - 3,
          f"{len(left)} of {len(mine)}")

    r = c.post("/api/recipes/delete-many",
               json={"ids": [x["id"] for x in left]}).json()
    check("the whole library can go", r["deleted"] == len(left))
    check("leaving nothing", not c.get("/api/recipes").json()["recipes"])

    r = c.post("/api/recipes/delete-many", json={"ids": []})
    check("an empty list is refused rather than obeyed", r.status_code == 422,
          str(r.status_code))

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
