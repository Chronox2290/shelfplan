"""The stylesheet has to parse, or half the design silently never applies.

An unclosed @media once swallowed sixty-odd rules -- the ingredient photos, the
recipe book, the scanner flash -- and nothing failed. It just did not appear.
"""
import io
import os
import sys

ROOT = os.path.join("C:" + os.sep, "Users", "chris", "coles-woolworths-mcp-server")
page = io.open(os.path.join(ROOT, "webapp", "static", "index.html"),
               encoding="utf-8").read()
css = page[page.index("<style>") + 7:page.index("</style>")]

fails = []
depth = line = 0
for ch in css:
    if ch == "\n":
        line += 1
    elif ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth < 0:
            fails.append(f"a closing brace with nothing open, at line {line}")
            break
if depth > 0:
    fails.append(f"{depth} block(s) left open at the end")

# Every rule the page depends on has to be reachable at top level, which is
# what an unclosed media query quietly takes away.
needed = [".food-pic", ".recipe-strip", ".book-grid", ".book-tile", ".auto-day",
          ".scan-flash", ".shop-name", ".chip", ".saved-row", ".ing-line",
          ".was", ".tag.when", ".toast", ".fold"]
depth = 0
top_level = set()
buf = ""
for ch in css:
    if ch == "{":
        if depth == 0:
            top_level.add(buf.split("*/")[-1].strip())
        depth += 1
        buf = ""
    elif ch == "}":
        depth -= 1
        buf = ""
    else:
        buf += ch
flat = " ".join(top_level)
for sel in needed:
    if sel not in flat:
        fails.append(f"{sel} is not a top-level rule")

for f in fails:
    print("  FAIL " + f)
if not fails:
    print(f"  ok   stylesheet parses, {len(top_level)} top-level rules")
sys.exit(1 if fails else 0)
