"""The stylesheet has to parse, or half the design silently never applies.

An unclosed @media once swallowed sixty-odd rules -- the ingredient photos, the
recipe book, the scanner flash -- and nothing failed. It just did not appear.
"""
import io
import os
import re
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
          ".tag.when", ".toast", ".fold",
          # The shelf ticket is the one element this product could not borrow
          # from another, and it now carries every price in the app -- the
          # shopping list, the price history, the catalogue search, the swap
          # sheet and the scanner. If its rules stop applying, five screens
          # lose their prices at once and nothing else fails.
          ".ticket", ".ticket-price", ".ticket-sign", ".ticket-cents",
          ".ticket-unit", ".ticket-flag", ".ticket.special", ".ticket.empty"]
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

# The other direction: a rule nothing emits any more. Harmless on its own, but
# it is the trace a half-finished change leaves behind -- when the shelf ticket
# took over the prices, five rules for the old red-tag treatment stayed in the
# file, still styling a class no code produced. Nothing failed; the stylesheet
# just quietly carried a dead design.
#
# Classes built by interpolation (`cat-${kind}`, `when-${meal}`) cannot be seen
# in the source, so a prefix that some rule extends is enough to keep it.
js = io.open(os.path.join(ROOT, "webapp", "static", "app.js"),
             encoding="utf-8").read()
markup = page[page.index("</style>"):]

emitted = set()
for src in (js, markup):
    # Matched to its own closing delimiter, because the attribute routinely
    # contains the other kind of quote: class="day${cond ? ' today' : ''}".
    for _, attr in re.findall(r"""class(?:Name)?\s*=\s*(["'`])(.*?)\1""", src):
        # Plain words, and the names hidden inside a conditional append such as
        # `class="day${isToday(date) ? ' today' : ''}"`.
        emitted.update(w for w in re.split(r"[\s${}]+", attr) if w)
        for lit in re.findall(r"""['"]([^'"]*)['"]""", attr):
            emitted.update(lit.split())
    for call in re.findall(r"classList\.\w+\(([^)]*)\)", src):
        emitted.update(re.findall(r"""['"]([\w-]+)['"]""", call))
    for sel in re.findall(r"""querySelector(?:All)?\(\s*['"`]([^'"`]+)""", src):
        emitted.update(re.findall(r"\.([\w-]+)", sel))
    for cls in re.findall(r"""className\s*=\s*([^;
]+)""", src):
        for lit in re.findall(r"""['"]([^'"]*)['"]""", cls):
            emitted.update(lit.split())

# A word in a class attribute may be a JS variable rather than a class name;
# only names some rule actually claims are judged, so that cuts both ways.
styled = set(re.findall(r"\.(-?[A-Za-z_][\w-]*)",
                        re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
prefixes = {w for w in emitted if w.endswith("-")}

# Three the search cannot see, each for a stated reason. Anything else that
# turns up here is a rule whose markup has gone.
allowed = {
    "big",   # foodPhoto(food, 'big') -- the class arrives as an argument
    "tile",  # foodPhoto(food, 'tile') -- likewise
    "btn",   # the second half of `button,.btn`, which styles real <button>s
}

for name in sorted(styled - emitted - allowed):
    if any(name.startswith(pre) for pre in prefixes):
        continue        # built by interpolation, e.g. cat-${kind}
    fails.append(f".{name} is styled but nothing emits it any more")

for f in fails:
    print("  FAIL " + f)
if not fails:
    print(f"  ok   stylesheet parses, {len(top_level)} top-level rules")
    print(f"  ok   every rule is still emitted by something ({len(styled)} classes)")
sys.exit(1 if fails else 0)
