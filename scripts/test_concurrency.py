"""Two devices, one plan: the later save must not flatten the earlier one."""
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
           json={"email": "two@example.com", "password": "a-long-enough-password"})
    made = c.post("/api/plans", json={"name": "T", "data": {"got": []}}).json()
    pid = made["id"]
    check("a new plan starts at version 1", made.get("version") == 1,
          str(made.get("version")))

    # Both devices load the same copy.
    phone = c.get(f"/api/plans/{pid}").json()
    laptop = c.get(f"/api/plans/{pid}").json()
    check("both copies agree on the version",
          phone["version"] == laptop["version"] == 1)

    # The phone ticks something off.
    r = c.put(f"/api/plans/{pid}",
              json={"data": {"got": ["Broccoli, raw"]},
                    "base_version": phone["version"]})
    check("the first save is accepted", r.status_code == 200, str(r.status_code))
    check("and moves the version on", r.json()["version"] == 2,
          str(r.json().get("version")))

    # The laptop, still holding version 1, tries to save something else.
    r = c.put(f"/api/plans/{pid}",
              json={"data": {"got": [], "week": ["something"]},
                    "base_version": laptop["version"]})
    check("a save from the older copy is refused", r.status_code == 409,
          str(r.status_code))
    detail = r.json().get("detail") or {}
    check("and the refusal carries the newer document",
          detail.get("data", {}).get("got") == ["Broccoli, raw"], str(detail)[:70])
    check("and the version to retry against", detail.get("version") == 2,
          str(detail.get("version")))

    after = c.get(f"/api/plans/{pid}").json()
    check("the ticked item survived the losing save",
          after["data"]["got"] == ["Broccoli, raw"], str(after["data"]))

    # Retrying against the version it was given works.
    r = c.put(f"/api/plans/{pid}",
              json={"data": {"got": ["Broccoli, raw"], "week": ["something"]},
                    "base_version": detail["version"]})
    check("retrying against the current version succeeds", r.status_code == 200,
          str(r.status_code))

    # A caller that omits the version is an older page; it still works.
    r = c.put(f"/api/plans/{pid}", json={"data": {"got": []}})
    check("a save with no version stated is still allowed through",
          r.status_code == 200, str(r.status_code))

    # Every writing endpoint has to move the version, or a page goes stale
    # without being told.
    before = c.get(f"/api/plans/{pid}").json()["version"]
    c.post(f"/api/plans/{pid}/undo")
    check("undo moves the version",
          c.get(f"/api/plans/{pid}").json()["version"] > before)

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
