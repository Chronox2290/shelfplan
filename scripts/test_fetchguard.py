"""Anything that fetches a caller-supplied URL must stay on the public net."""
import os
import sys

sys.path.insert(0, os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server"))

from src.supermarkets import recipe_import, safefetch  # noqa: E402

fails = []


def check(label, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


print("the guard itself")
for bad in ("http://127.0.0.1/x", "https://localhost/x", "https://192.168.1.1/x",
            "https://10.0.0.1/x", "https://169.254.169.254/x", "https://[::1]/x"):
    try:
        safefetch.check_url(bad, schemes=("http", "https"))
        check(f"refuses {bad}", False, "it was allowed")
    except safefetch.Refused:
        check(f"refuses {bad}", True)
    except Exception as exc:                       # unresolvable is fine too
        check(f"refuses {bad}", True, type(exc).__name__)

try:
    safefetch.check_url("https://example.com/x")
    check("allows a public https address", True)
except safefetch.Refused as exc:
    check("allows a public https address", False, str(exc))

try:
    safefetch.check_url("http://example.com/x")
    check("refuses http when only https is asked for", False, "allowed")
except safefetch.Refused:
    check("refuses http when only https is asked for", True)

print("the recipe importer uses it")
for bad in ("http://127.0.0.1:8000/api/version", "http://192.168.1.1/"):
    r = recipe_import.fetch(bad, timeout=3)
    check(f"importer refuses {bad[:34]}",
          r["status"] == "error" and "private network" in r.get("message", ""),
          str(r.get("message"))[:52])

print("the image proxy uses the same one")
from webapp import imageproxy  # noqa: E402
check("proxy shares the guard's exception type",
      imageproxy.Refused is safefetch.Refused)

print()
print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
