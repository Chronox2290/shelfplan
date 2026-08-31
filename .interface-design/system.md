# Design System — Shelf Plan

Written for the `interface-design` skill, which reads this before touching UI.
Decisions here are made; hold to them rather than re-deciding.

## The human

Christian, meal-prepping to numbers — 1900 kcal, 150g protein, 25g fibre a day —
and to a budget, around $100–120 a week at Woolworths. Two quite different
moments:

* **Planning**, at a desk, unhurried, deciding a week and pricing it.
* **Shopping**, in an aisle, one-handed on a Pixel, trolley in the other hand,
  wanting to find the next line and tick it off without stopping.

The second is the harder brief and the one that keeps being got wrong. A
control that is comfortable with a mouse is not necessarily hittable with a
thumb while holding a trolley.

Also shared with a friend running it on a NAS, so nothing may assume one user
or one device.

## The verb

Plan a week that hits the numbers, then buy it for the money. Everything
serves *plan*, *price*, or *shop*.

## Feel

Not a dashboard, and specifically not a fitness app. It sits between a kitchen
notebook and a supermarket shelf. Warm paper, herb green, plain figures. Quiet
enough to read in a shop, ordinary enough not to feel like tracking software.

## Domain

Concepts this product's world actually contains: the trolley, the aisle, the
shelf-edge ticket, price per kilo, the pack you cannot buy half of, the
meal-prep container, the weekly shop, the receipt, the specials that change on
a Wednesday, the fridge shelf.

## Colour world

Where those colours come from: fresh produce green, kraft-brown packaging,
the cold white-blue of the refrigerated aisle, black-on-white receipt print,
the red and yellow of a special ticket, stainless steel.

The red is deliberately reserved. It is the specials colour in every
Australian supermarket, so it is used here for one thing only — a price that
has moved — and never for decoration.

## Tokens

Names come from the world, not from a palette generator: `--ink`, `--ground`,
`--panel`, `--sunk`, `--rule`, `--hair`, `--accent`, `--warn`, `--stop`.
Reading the token list should suggest paper and shelves. Never `--gray-700`.

### Radius — four, and no more

```
--r-sm   6px    things you type into, and small controls
--r-md  10px    things that hold content: cards, rows, panels
--r-lg  14px    things that float above the page: sheets, dialogs
--r-pill        tags and chips
```

Before this there were eleven values, which is not a scale.

### Spacing

Base 4px, used in multiples. Card padding 20px desktop, 15–16px phone.

### Depth — borders and tone, not shadows

One strategy, committed to. Structure comes from a 1px `--rule` or `--hair`
and from a tonal step between `--ground`, `--panel` and `--sunk`. Shadows are
for things that genuinely lift off the page — sheets, the toast, a hovered
book tile — and nothing else. Dark mode drops the depth shadows entirely and
keeps the ring, because depth shadows do not read on dark.

### Type

Archivo for headings, Source Sans 3 for body, IBM Plex Mono for figures.
Body 17px — raised from 16 because most of this app is secondary text and 13px
secondary text is a squint on a phone.

`font-variant-numeric: tabular-nums` on the root. Nearly every number here
changes, and proportional digits make a column twitch as it updates.

### Motion

```
--ease-out   cubic-bezier(.23,1,.32,1)    things arriving
--ease-move  cubic-bezier(.77,0,.175,1)   things already here, moving
```

Under 200ms for anything routine. `scale(.97)` on `:active` so a tap answers.
Everything drops under `prefers-reduced-motion`.

## Hierarchy

One focal element per view, and it wins on weight and colour before size:

* **Shopping list** — the item name. Largest thing on its row (17.5px/600),
  because that is what you are scanning for in an aisle. Price is monospaced
  and secondary; store and controls are quieter still.
* **A day** — the day's macro line, then each meal's own figures, then the
  ingredients. You can read what Tuesday is by looking at Tuesday.
* **A recipe card** — the name, then the macros, with the method folded away.
  A library is scanned, not read.

Three tiers from weight and colour at one size beats three sizes at one
weight.

## Hit targets

40px minimum for anything tappable, and the compact 30/34px look returns only
under `@media (pointer:fine)`. This is not a general accessibility gesture; it
is the aisle.

## Patterns worth keeping

* `Button` — 40px min height · 9px 15px padding · `--r-md` · 600 weight.
* `.tag` — `--r-pill` · 5px 11px · 12px. Meal-of-day tags use `.when`, never
  `.meal`, which is already a shopping row.
* Shopping row — thumbnail · name (17.5px/600) · quantity and matched product
  beneath · price · per kg · store · swap/remove.
* A missing photograph falls back to a glyph for the kind of food, never a
  letter. Handled by one capture-phase listener, never an inline `onerror`.

## Standing rules

* Never `loading="lazy"` inside the scrolling panels — it never fires there and
  the image silently never loads.
* Every colour comes from a token defined on bare `:root`, so all three theme
  states resolve.
* `scripts/test_stylesheet.py` guards the brace balance and that every rule the
  page depends on is reachable at the top level. An unclosed `@media` once
  swallowed sixty rules in silence.
