# Shelf Plan

Meal planning, recipes and a shopping list priced against Woolworths and Coles.
Runs entirely on your own machine -- a PC, a Raspberry Pi, or a NAS.

- **Plan a week** on a calendar, from a recipe library you rate and curate.
- **Build recipes** to calorie, protein, carb, fat and fibre targets, with
  cuisine themes, or **import one** from a recipe site by pasting its address.
- **Price the shopping list** at both supermarkets, with product photos, links
  back to the store, editable prices and a per-item price history.
- **Tick items off** as you shop, on your phone.

Accounts, password reset, a product catalogue that builds itself, and a
double-click launcher so none of it needs a terminal.

## Credit

Built on top of [coles-woolworths-mcp-server](https://github.com/hung-ngm/coles-woolworths-mcp-server)
by hung_ng__, MIT licensed, which provided the original Woolworths and Coles
search clients and the MCP server they are exposed through. That licence is
kept in `LICENSE` and applies to this work too.

The MCP server still works and is documented below; the web application is
built on the same supermarket clients.

<a href="https://glama.ai/mcp/servers/@hung-ngm/coles-woolworths-mcp-server">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@hung-ngm/coles-woolworths-mcp-server/badge" alt="coles-woolworths MCP server" />
</a>

## Demo

### Use with Claude Desktop

https://github.com/user-attachments/assets/0af3b07a-578a-4112-acfe-e7a7eee31161

## Features

- **Product Search**: Search for products at both Coles and Woolworths supermarkets
- **Price Comparison**: Get pricing information from both retailers in a consistent format
- **Store Selection**: Search specific Coles stores using store IDs
- **Result Limiting**: Control how many products are returned in search results

## Quick Start for Claude Desktop, Cursor, and other clients

1. Clone this repository
```bash
git clone https://github.com/hung-ngm/coles-woolworths-mcp-server.git
```

2. Navigate to the project directory
```bash
cd coles-woolies-mcp
```

3. Install the [prerequisites](#prerequisites)

4. Configure your MCP client to use this server (see [Integrating with MCP Clients](#integrating-with-mcp-clients))

## Installation

### Prerequisites

1. Python 3.8 or higher
2. The `uv` package manager

### Installing uv

uv is a fast Python package installer and resolver. To install:

#### macOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Windows:
```bash
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Setup

1. Clone the repository and navigate to the project directory
2. Use `uv` to install dependencies:

```bash
# Install dependencies
uv pip install fastmcp requests python-dotenv
```

## Configuration

The server uses the following environment variables:

- `COLES_API_KEY`: API key for accessing the Coles API (required for Coles product searches)

You can set these variables in a `.env` file in the project directory.

## Running the Server

To run the Coles and Woolworths MCP server directly using `uv`:

```bash
uv run main.py
```

By default, the server runs with stdio transport for MCP client integration.

## Integrating with MCP Clients

### Claude Desktop Configuration

To use the Coles and Woolworths MCP server with Claude Desktop:

1. Locate your Claude Desktop configuration file (usually `claude_desktop_config.json`)
2. Add the following configuration to the `mcpServers` section:

```json
{
  "mcpServers": {
    "coles-woolies-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "fastmcp",
        "--with",
        "requests",
        "--with", 
        "python-dotenv",
        "fastmcp",
        "run",
        "/full/path/to/coles-woolies-mcp/main.py"
      ]
    }
  }
}
```

Replace `/full/path/to/coles-woolies-mcp/main.py` with the absolute path to your main.py file.

3. Restart Claude Desktop for the changes to take effect

### Cursor IDE Configuration

To integrate with Cursor IDE:

1. Open your Cursor configuration file
2. Add the following to the `mcpServers` section:

```json
{
  "mcpServers": {
    "coles-woolies-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "fastmcp",
        "--with",
        "requests",
        "--with", 
        "python-dotenv",
        "fastmcp",
        "run",
        "/full/path/to/coles-woolies-mcp/main.py"
      ]
    }
  }
}
```

## Available Tools

The Coles and Woolworths MCP server exposes the following tools:

- `get_coles_products`: Search for products at Coles supermarkets with optional store selection
- `get_woolworths_products`: Search for products at Woolworths supermarkets

### Example Usage in Claude

You can use the tools in Claude like this:

```
Could you check the price of Cadbury chocolate at both Coles and Woolworths?
```

Claude will then use the appropriate tools to search for the products and return the results.

## Requirements

- Python 3.8 or higher
- fastmcp package
- requests package
- python-dotenv package
- MCP-compatible client (Claude Desktop, Cursor, etc.)
---

## Meal-plan integration

Added on top of the original two tools, for costing a meal plan rather than
eyeballing a price.

### Why the extra layer

The original `get_woolworths_products` returns a bare unit string (`"g"`) with
no magnitude, and treats the API's `Price` field as a pack price. That is wrong
for variable-weight lines: a fillet listed as `per 350g` carries `Price=12`
meaning **$12/kg**, not $12 for the pack. The store publishes `CupPrice`,
`CupMeasure` and `UnitWeightInGrams`; this layer uses them.

It also keeps two distinctions a meal plan depends on:

* **Pack size.** A 500g and a 1.5kg chicken pack differ ~30% per kilo, so the
  match closest to the pack you actually buy wins.
* **Drained weight.** A food recorded as `"..., drained"` holds drained mass
  while the shelf pack is the gross tin. Comparing across those bases reports a
  40% price drop that never happened.

### Tools

| Tool | Returns |
|---|---|
| `search_woolworths` | JSON products with `pack_g`, `per_kg`, specials, stock |
| `price_planned_food` | One food priced on the plan's basis, with `confidence` and `needs_review` |

Never overwrite a hand-checked figure when `needs_review` is set.

### HTTP service

```bash
uv run uvicorn service.api:app --port 8000
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /search?q=&limit=` | normalised search |
| `GET /price?food=&query=&pack=` | one food on the plan's basis |
| `POST /prices` | batch; splits `auto` / `review` / `failed` |

CORS is open because it binds to localhost. Note that a **published Claude
artifact cannot call this** — the artifact CSP blocks all external hosts,
localhost included. Use it from a page opened off disk, or refresh the plan
with the script below.

### Refreshing a plan file

```bash
uv run python scripts/refresh_prices.py shelf-plan.html -o updated.html
uv run python scripts/refresh_prices.py shelf-plan.html --dry-run
```

Appends a dated record to each food's price history rather than rewriting it,
so the history survives and a bad match is rolled back by dropping the newest
entry. Foods flagged `needs_review` are reported and left untouched.

### Coles -- no API key needed any more

**Do not chase a `COLES_API_KEY`.** The `/api/bff/products` route the original
code used needs a `subscription-key` that Coles no longer exposes to the
browser: product search is rendered server-side now, so the browser never makes
that call and never holds the key.

(If you tried extracting a 32-hex string from the page, note the build id
contains a 40-character git SHA. A naive `[0-9a-f]{32}` match returns the first
32 characters of that SHA, which is not a key and returns HTTP 401.)

Instead, `coles_catalog.py` reads the products straight out of the search
page's `__NEXT_DATA__` payload. No key, no account.

Two things to know about it:

* **Coles rate-limits server-side requests.** Too many too quickly and the site
  serves a "Pardon Our Interruption" interstitial instead of results, and the
  block outlasts the burst by several minutes. Requests are therefore
  serialised with a 1.8s gap and cached for 30 minutes. Treat Coles as
  best-effort: it is genuinely correct when it answers, and the app degrades to
  Woolworths-only when it does not.
* **Their structured unit price is unreliable.** Some rows carry
  `ofMeasureType: "g"` with `ofMeasureQuantity: 1` while the displayed
  comparable price reads `$14.50/ 1kg`. Believing the structured block gives
  $14,500/kg, so the displayed string wins and the block is only a fallback.

Woolworths has neither problem and is the dependable source.

---

## Running it as a web app

The MCP server and HTTP service above are for tools. This is the app people use:
a meal plan, recipe list, shopping list and price check, with accounts so it
syncs across devices.

Serving the page from the same origin as the API is what makes this work at all
-- a published Claude artifact cannot call any external host, localhost
included, but a page served by this app is same-origin and has no such limit.

### Sharing it publicly

See **[DEPLOY.md](DEPLOY.md)** -- Fly.io in about five commands, or your own
server with automatic HTTPS. Public hosting is what activates the install-to-
home-screen behaviour: browsers only register a service worker over HTTPS.

### Quick start with Docker

```bash
cp .env.example .env
# Generate a secret and paste it into .env as SESSION_SECRET:
openssl rand -base64 48

docker compose up -d
```

Then open <http://localhost:8000> and create an account.

`SESSION_SECRET` is required -- compose refuses to start without it. Changing it
signs everyone out. Data lives in the `shelfplan-data` volume, so `docker compose
down` keeps it and `docker compose down -v` destroys it.

### Without Docker

```bash
uv sync
SESSION_SECRET="$(openssl rand -base64 48)" COOKIE_SECURE=0   uv run uvicorn webapp.app:app --port 8000
```

### Importing an existing plan

```bash
uv run python scripts/import_plan.py shelf-plan.html --email you@example.com
```

Accepts a plan `.html` (reads its `<script id="state">` block) or raw `.json`,
and creates the account if it does not exist. You can also paste the JSON into
the app's **Data** tab.

### API

All routes need a session cookie except `/api/health`.

| Route | Purpose |
|---|---|
| `POST /api/auth/register` · `login` · `logout` | accounts |
| `GET /api/auth/me` | current user |
| `GET POST /api/plans` | list / create |
| `GET PUT DELETE /api/plans/{id}` | read / update / delete |
| `POST /api/plans/{id}/refresh-prices` | re-price the shopping list |
| `GET /api/search?q=&store=` | search both stores, cheapest first |
| `GET /api/compare?food=&query=&pack=` | one food priced at both, with the saving |
| `POST /api/recipes/generate` | build recipes to targets and cost them |
| `GET /api/price?food=&query=&pack=` | one food on the plan's basis |
| `GET /api/price-history?food=` | observed prices over time |

Refresh appends one reading per food per day, and holds back low-confidence
matches unless you pass `{"apply_reviewed": true}`.

### Security notes

Built in: Argon2id password hashing, signed http-only session cookies,
per-user ownership checks on every plan route (a stranger's plan id returns 404,
not 403, so ids cannot be probed), and registration messages that do not reveal
whether an address already has an account.

Before putting it on the internet:

* **Serve over TLS and set `COOKIE_SECURE=1`.** The default `0` suits localhost
  only; over plain http a session cookie travels in clear.
* **Set a strong `SESSION_SECRET`** and keep it out of version control.
* **Consider switching to Postgres** via `DATABASE_URL`. SQLite is fine for a
  household, less so for concurrent writers.
* There is no rate limiting on login, no email verification and no password
  reset. Add them, or keep the app on a private network or behind an
  authenticating proxy such as Tailscale or Cloudflare Access.

### Docker Desktop Extension

Not built. A Docker *Extension* is a separate packaging format (an extension
`metadata.json`, a UI built against the Docker Extension SDK, and publication to
the Marketplace) rather than a flag on this image. The compose file above already
gives you the "runs off my Docker setup" part; say the word if you want the
Extension wrapper on top.

## Recipe builder

`POST /api/recipes/generate`, or the **Recipe builder** tab.

Recipes are composed, not retrieved. A template picks one ingredient per role,
then quantities are solved so each serving meets your protein target first and
your calorie target second. Every gram maps to a shopping-list line, and every
line is priced at both supermarkets.

```json
{"seed": "week-1", "meals": 5, "servings": 4,
 "kcal_per_serving": 600, "protein_per_serving": 40,
 "diet": "vegetarian", "exclude": ["mushrooms"], "price": true}
```

`diet` is one of `any`, `pescatarian`, `vegetarian`, `vegan`.

Ingredients declare which templates they suit, so oats stay out of a stir-fry
and tinned beans out of a tray bake. Condiments carry their own serving size --
a splash of soy is 15g, a jar of passata 120g -- rather than one blanket amount.

**Recipes report their own misses.** A low-density protein hits its sensible
gram ceiling before a high protein target, so the recipe carries a `notes` entry
saying so instead of presenting a miss as a match:

> Chickpeas tops out at 28g protein per serving, short of the 40g target.

The totals distinguish buying everything at one store from splitting the shop:
`totals.byStore` is each single-store basket, `totals.cheapestMixed` takes the
cheaper store per line. Nutrition figures are approximate and for planning only.

## What it runs on

It is a web app, so it already runs everywhere: Windows, macOS, Linux, iOS and
Android, in any current browser. There is no platform-specific code and no app
store involved.

It is also an installable PWA. Add to the home screen and it opens
full-screen with its own icon, no browser chrome -- close enough to a native app
for this purpose.

* **Android / Chrome / Edge** -- an **Install** button appears in the header.
* **iOS / Safari** -- Share, then *Add to Home Screen*. Safari never fires the
  install event, so the button stays hidden there by design.
* **Desktop** -- install from the address-bar icon in Chrome or Edge.

The service worker caches only the app shell, never `/api/` responses. Offline
the app opens and reports that it cannot reach the server, rather than
presenting last week's prices as current.

### Reaching it from a phone

The real constraint is not the platform, it is the network. Pick one:

| How | Reach | Notes |
|---|---|---|
| `docker compose up` on your PC | That PC only | `http://localhost:8000` |
| Same Wi-Fi | Phones at home | Use the PC's LAN IP, e.g. `http://192.168.1.20:8000`. Set `SHELFPLAN_PORT` and allow the port through the firewall. |
| **Tailscale** (recommended) | Your devices, anywhere | Private network, TLS via MagicDNS, nothing exposed publicly. Set `COOKIE_SECURE=1`. |
| Cloudflare Tunnel | Anyone you allow | Public hostname without opening a port; put Cloudflare Access in front. |
| A small VPS | Anyone | You own the security: TLS, `COOKIE_SECURE=1`, rate limiting, backups. |

An installed PWA still needs the server reachable, so a phone on mobile data
needs Tailscale, a tunnel, or a hosted instance -- installing does not make it
work offline beyond the shell.

Note that iOS evicts PWA storage after a few weeks of non-use. That is harmless
here because plans and prices live on the server, not in the browser.

### Regenerating the icons

```bash
uv run python scripts/make_icons.py
```

Pure `zlib`, no image library, so it works in the container too.

## Password reset

`Forgot password?` on the sign-in page, or `POST /api/auth/forgot`.

* Tokens are stored only as a **SHA-256 hash**, so a leaked database or backup
  yields hashes that cannot be presented.
* Requesting a reset **never reveals whether an address has an account** --
  same response either way. It is not a membership oracle.
* A token is **single use**, expires after `RESET_TTL_MINUTES` (default 60),
  and issuing a new one retires the old.
* Redeeming **signs out every other session** for that account. Without this,
  resetting a stolen account would leave the thief's cookie working. The same
  applies to `POST /api/auth/change-password`.
* Reset requests are rate limited per IP *and* per account, so one address
  cannot be mail-bombed from many machines.

### Without an SMTP server

Most home installs have no mail relay, and a reset that only works with one is
a reset that does not work. So when SMTP is unconfigured, the message is
**written to the server log** instead:

```bash
docker compose logs shelfplan | grep reset=
```

Whoever runs the box reads the link out and passes it on. That is a deliberate
trade-off for self-hosting -- and it does mean anyone who can read the logs can
take over an account, which is why the app says so at startup rather than
hiding it. Configure `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` for
real delivery.

Set `PUBLIC_URL` so the link points at the address people actually use --
behind a proxy the request's own host is the internal one.

## Running it on a NAS

Yes -- that is exactly what this is. A NAS running the container **is** their
own server: the data lives on their disk, in their house, under their control.
No account with me or anyone else, and no third party holding the plans.

Synology (Container Manager), QNAP (Container Station), Unraid, TrueNAS Scale
and any Proxmox LXC all run `docker compose` files. Point them at this repo:

```bash
git clone <this repo> && cd coles-woolworths-mcp-server
cp .env.example .env      # set SESSION_SECRET
docker compose up -d
```

What "accessible" means then depends on how far they want it to reach:

| Scope | How | Notes |
|---|---|---|
| On the home network | `http://nas.local:8000` | Works immediately. `COOKIE_SECURE=0`. |
| Their own devices anywhere | **Tailscale** on the NAS | Best answer for a household. Private, TLS, nothing exposed. `COOKIE_SECURE=1`. |
| Anyone they invite | Cloudflare Tunnel, or `docker-compose.prod.yml` with Caddy | Public hostname and a real certificate. Use `SIGNUP_MODE=invite`. |

Each NAS is a separate island -- accounts and plans do not sync between one
household's server and another's. That is the point of self-hosting, but it
means a household should run one instance and make accounts on it, rather than
one instance each.

One caveat for NAS hardware: Coles and Woolworths lookups leave from the NAS's
IP, and Coles rate-limits. A household hammering refresh will trip it for
everyone on that connection. The per-user refresh cap exists for this.

### ARM NAS boxes

The image builds from `python:3.12-slim`, which is multi-arch, so it works on
arm64 (most modern Synology/QNAP) as well as x86. Build on the NAS itself, or
`docker buildx build --platform linux/arm64`.

## Sharing it with other people

Two problems have to be solved together: the supermarkets must not see more
traffic as you add users, and people need to reach the thing from a phone.

### Why more users did not mean more scraping

Every lookup leaves from *this server's* address, so without something in
between, ten users cost ten times the upstream requests and Coles blocks the
lot of you. Three mechanisms handle it:

**A shared cache in the database.** Keyed by store and search term, never by
user, so everyone looking up "rolled oats" costs one request per refresh
window. Verified: twelve accounts searching the same term produced exactly one
call per store. It lives in the database rather than memory, so a restart does
not re-trigger a burst. `PRICE_CACHE_HOURS` (default 12) sets the window --
shelf prices move daily at most.

**A circuit breaker.** Coles answers a burst with a challenge page, and
retrying through it extends the block. After `BREAKER_FAILURES` (3) consecutive
failures the breaker opens and stops calling that store for
`BREAKER_COOLDOWN_MINUTES` (20), then lets one request through to test. This
matters more than it sounds: retrying is what turns a short block into a long
one.

**Stale beats empty.** When a store is paused or failing, the last known prices
are served with their age attached -- "prices from yesterday" -- up to
`PRICE_STALE_HOURS` (default 168). The UI labels each store as *just checked*,
*checked 3h ago*, *prices from yesterday*, or *unavailable*. An old price you
can see the age of is useful for planning; a blank cell is not. A stale price is
never presented as a current one.

`GET /api/price-cache` reports what is cached and whether a store is paused.

Woolworths has no such problem and is the dependable source. Treat Coles as a
bonus that arrives when it arrives.

### Getting it onto their phone

| Who is using it | Best option | Why |
|---|---|---|
| You and your household | **Tailscale on the host** | Install Tailscale, share the machine to their account. They open `http://shelfplan:8000` from anywhere. Private, free for personal use, no ports open, no DNS, no certificate. |
| A few friends | **Cloudflare Tunnel** | Real hostname and certificate without exposing a port. Pair with `SIGNUP_MODE=invite`. |
| Anyone | **Fly.io** (`fly.toml`) | Public `*.fly.dev` URL with TLS. See DEPLOY.md. |

For anything beyond your own LAN, set `COOKIE_SECURE=1` and `PUBLIC_URL`, and
leave `SIGNUP_MODE=invite`.

**HTTPS is what makes it feel like an app.** Browsers refuse to register a
service worker over plain http (localhost excepted), so install-to-home-screen
stays dormant until you are on a real certificate. Once you are: Android and
desktop Chrome show an **Install** button in the header; on iOS it is Share →
*Add to Home Screen*. After that it opens full-screen with its own icon and
behaves like any other app on the phone.

Nothing needs installing on their computer -- it is a URL in a browser.

## Recipe library

Generated recipes are saved to a library that outlives any one week's plan.

* **Full detail on every card** -- per-serving kcal, protein, carbs, fat and
  fibre; how many servings it makes; per-serving *and* total grams for each
  ingredient; numbered method steps.
* **Storing and reheating**, which is the point of meal prep. Each template
  carries its own, because dishes differ: a tray bake dries out and wants a
  splash of water, a stir-fry is better in a pan than a microwave, a ragu
  spits and needs covering, a soup needs its middle checked. Fridge and
  freezer life, from-fridge timings at 800W, and from-frozen where it applies.
* **Rate them 1-5.** Rated recipes sort to the top, so the ones that worked
  are the ones you see first. Unrated is distinct from badly rated.
* **Delete the ones you did not like**, with a confirmation.
* **"Cooked it"** increments a counter, so you can see what actually gets made.

`GET/POST /api/recipes`, `PATCH /api/recipes/{id}` (rating, notes, cooked),
`DELETE /api/recipes/{id}`. A library is private to its owner: another account
gets a 404 on every one of those.

## Planning a week

The **Week** tab builds a schedule from your library rather than needing
imported data. Pick a recipe and a serving count for each day, and it totals
the energy across the week. **Build shopping list** rolls every planned meal up
into one line per ingredient -- scaled by servings, grouped by aisle, with the
number of packs to buy -- and drops it into the Shopping list tab.

## Shopping list

* **Tick items into your basket as you shop.** Ticked rows grey out and strike
  through, and the total splits into *basket total* and *still to get*. The
  ticks are saved to your account, so the list survives locking your phone.
* **A link on each line** back to the product page the price came from.
* **Edit any price.** Corrections are stored as manual readings alongside the
  scraped ones, so they appear in the history and the graph rather than being
  overwritten on the next refresh.

## Price history and whether it is a good week

The **Prices** tab draws a sparkline per food from its readings -- inline SVG,
no chart library, so nothing external loads. A light dot marks the cheapest
reading, a dark dot marks now.

Each food gets a verdict, judged against *its own usual price* rather than an
all-time low, because "cheapest ever" is rare and unhelpful while "cheaper than
usual" is what decides whether to buy this week:

| Verdict | Means |
|---|---|
| cheapest yet | Lowest of every reading so far |
| good week to buy | 8% or more below its usual |
| about normal | Within 8% either way |
| dearer than usual | 8% or more above its usual |
| highest yet | Dearest reading so far |

The trend needs at least two readings, so it fills in as you refresh week to
week.

## Importing a plan

The **Data** tab takes a plan `.html` **directly** -- drop it on the page or
pick it with the file chooser, and the state block is pulled out for you. A
`.json` export works the same way, and pasting is still there behind a
disclosure. Importing merges rather than replaces, so sections the file does
not mention survive.

Also there: download this plan, download your recipe library, and reset a plan
(which leaves the library and price history alone).

## Where to run it

### Not on an older PowerPC Synology (DS213+ and similar)

The DS213+ cannot run this, and not for a fixable reason. Its CPU is a
Freescale P1022 -- **PowerPC**, not x86 or ARM -- and Synology never shipped
Docker or Container Manager for PowerPC models. It also has 512 MB of RAM and
tops out at DSM 6.2, which reached end of life on 1 October 2024 and no longer
receives security patches. There is no build of this image, or of Docker, that
would run there.

A newer Synology with an x86 or ARM64 CPU and Container Manager runs it fine.

### Cloud hosting works, but expect to lose Coles

Coles sits behind **Imperva** (visible as `X-CDN: Imperva` on their responses),
which scores requests and serves a "Pardon Our Interruption" page to anything it
dislikes. Datacenter address ranges are exactly what such systems distrust, so a
cloud-hosted instance should expect Coles to be blocked most or all of the time.

Even from a home connection it is intermittent. In one minute of testing, a
search for "milk" returned the full 629 KB page while "rolled oats" came back as
a 6 KB challenge. This is why Coles is treated as best-effort throughout: shared
cache, circuit breaker, and stale-with-age rather than a blank.

Woolworths has no such CDN in front of it and should keep working from anywhere.

So: **hosting in the cloud means a Woolworths-only price feed**, with Coles
appearing occasionally if at all. The app degrades to exactly that already.

### The options, ranked for this use

| Option | PC can be off | Coles works | Notes |
|---|---|---|---|
| **Small always-on box at home** (Raspberry Pi 4/5, mini PC) | yes | yes | Keeps the residential IP, which is the only thing that makes Coles viable. 3-6 W. Reach it with Tailscale. **Best fit.** |
| Newer Synology with Container Manager | yes | yes | Same reasoning, if you were replacing the NAS anyway. |
| Fly.io (`fly.toml` included) | yes | rarely | Public HTTPS URL, TLS handled, no hardware. Woolworths-only in practice. |
| Your Windows PC | no | yes | What it does today. |

A Raspberry Pi 5 with an SD card is roughly the price of two weeks of the
grocery savings this thing is meant to find, draws about as much power as a
phone charger, and keeps both stores working.

## Opening it without a terminal

Double-click **Shelf Plan.bat**, or the desktop shortcut it offers to create on
first run. A window opens with Start, Open in browser, Stop, and a Settings
dialog for the port, who may sign up, and the email account for password
resets -- so nothing routine needs a command prompt or a text editor.

It starts Docker Desktop itself if that is not already running, and reports
progress in a log pane rather than a black console. The Docker build runs in a
background job so the window stays responsive while it works.

On Linux and Raspberry Pi the equivalent is one command:

```bash
bash install.sh
```

It checks the machine is 64-bit with enough memory, installs Docker if missing,
generates a login secret, builds, starts, and prints the address to open.

## The product catalogue

The supermarkets publish no bulk export, so there is no database to download.
This builds one instead, and it grows two ways:

* **From use.** Every search -- yours or anyone else's on this server -- stores
  its results permanently. Ordinary shopping fills the index on its own.
* **From seeding.** `scripts/stock_catalogue.py` walks a list of everyday
  grocery terms and keeps what comes back.

```bash
docker compose exec shelfplan python scripts/stock_catalogue.py
docker compose exec shelfplan python scripts/stock_catalogue.py --store woolworths --delay 2
```

45 search terms yielded 1,303 products in about two minutes. The full term list
is roughly three times that.

The **Find food** tab searches it instantly with no network access -- so it
keeps working while a store is rate-limiting us -- and can filter to one store,
to specials only, and sort by price per kilo. **Add** puts a product on the
shopping list with its pack size, current price and a link back to the store
page. The other mode on that tab queries the stores live, and anything it finds
joins the index.

### What this is not

It is not a mirror of either supermarket. Woolworths alone reports tens of
thousands of matches for broad terms, requests are capped at 36 products each,
and Coles blocks sustained crawling outright -- so a complete copy is not
achievable from one address, and would be stale within a week if it were. What
you get is a growing index of what you and your household actually buy, which
is the part worth having.

Woolworths caps `pageSize` at 36 and answers 400 above that. The circuit
breaker deliberately ignores 4xx responses other than 403 and 429, so a bad
request here cannot take a store offline for twenty minutes.

## Planning a week

The week is a calendar: seven dated cards, today outlined, arrows to move
between weeks. **+ Add a meal** opens a picker rather than a dropdown, because
a flat list of recipes gets unusable at about a dozen.

The picker groups by what the meal actually is:

* **Favourites** first -- anything rated 4+ or cooked twice or more. That is
  what the cook counter is *for*: it earns a recipe a place at the top.
* Then **Chicken, Beef, Pork, Lamb, Fish & seafood, Vegetarian**, each with a
  colour dot that also appears on the calendar and on recipe cards.
* A filter box for when you know the name.

The category is derived from the main protein rather than stored, so it stays
correct if a recipe changes, and older recipes saved before categories existed
are grouped correctly on the way out rather than collapsing into "Other".

The cook counter has **+ and −**. A mis-click is undoable, and it will not go
below zero.

## Choosing rather than accepting

**Offer me choices** in the builder proposes three meals labelled A, B and C,
all built to your targets, and you keep the ones you want. **Offer more**
proposes another three. Options are separated by *category*, not by ingredient:
two chicken dishes are not a choice, so each option brings a different main.

## Product pictures

Photos appear in Find food, the catalogue and the shopping list. Items added
from the catalogue bring their picture with them; items from a recipe or an
import get one attached the next time prices are refreshed. Anything without a
photo shows a lettered tile rather than a broken image.

Two things this needed:

* **The CSP had to be opened** for the store image CDNs. The default
  `img-src 'self' data:` blocks every external image, which is exactly what a
  strict policy should do -- so the two hosts are named explicitly and nothing
  else is allowed.
* **Medium images, not small.** The `small` variant is a 40px thumbnail that
  looks blurry at any usable size; `medium` is ~9 KB against ~100 KB for
  `large`.

## Keeping Coles working

The honest answer to the blocking is that no single trick fixes it. What
actually helps, in order of how much difference it makes:

1. **Run it on a home connection.** A Raspberry Pi on a residential IP is
   treated very differently from a datacenter. This matters more than
   everything else combined.
2. **Never fetch in bursts.** The shared cache and the circuit breaker already
   stop the app hammering, and `TRICKLE=1` goes further: one background request
   every couple of minutes, jittered, forever. The catalogue fills in while
   nobody is waiting, which is the opposite of the burst that triggers a block.
3. **Read from the catalogue, not the store.** Once a product is indexed, Find
   food answers instantly from the local database. Being blocked stops being
   something you notice.

```bash
TRICKLE=1                      # in .env
TRICKLE_INTERVAL_SECONDS=120   # slower is safer
TRICKLE_STORES=coles,woolworths
```

`GET /api/trickle` reports whether it is running and what it has added.

What will not work: proxies and rotating addresses are against the spirit of
the thing and get an IP range blocked rather than one address; and there is no
public API to ask for instead. Coles remains best-effort by design.

## Giving someone their own copy

Their machine, their data, their home connection. Two files and one command.

```bash
docker compose -f docker-compose.nas.yml up -d
```

`docker-compose.nas.yml` **pulls** a published image rather than building one.
A NAS or Pi takes 15-40 minutes to compile Python packages for ARM; pulling a
prebuilt multi-arch image takes about a minute.

They do **not** need your Tailscale, and your machine does not need to be on.
The two installations are independent -- separate accounts, plans and price
history. Tailscale only matters for reaching *your* instance.

### Updates reach them on their own

The compose file includes **Watchtower**, which checks hourly for a newer image
and restarts into it. You publish; their NAS follows within the hour with
nothing for them to do. It is scoped by label, so it can only ever touch this
container and never anything else on their NAS.

Publishing is a GitHub Actions workflow (`.github/workflows/publish.yml`): a
push to `main` builds for `linux/amd64` and `linux/arm64` and pushes
`:latest`; tagging `v1.2.3` also publishes `:v1.2.3` and `:1.2` so a version
can be pinned. It authenticates with the workflow's own token, so no personal
access token with extra scopes is needed.

### Shared instance or separate copies

| | Separate copies | One shared instance |
|---|---|---|
| Data | Each household's own | Everyone on one server |
| Coles | Works -- their home IP | Works if the host is at home |
| Updates | Watchtower, within the hour | Instant, you rebuild once |
| Setup for them | Compose file on their NAS | Open a link |

Separate copies suit two households that shop separately. A shared instance
suits people planning the same meals.

### Before publishing anything

`.gitignore` covers `data/`, `backups/`, `*.db`, `.env`, exported meal plans
and the launcher's local state. The database holds accounts and Argon2 password
hashes and must never reach a repository, public or private. Check what a
commit would contain before the first push:

```bash
git status --short
git check-ignore .env data/shelfplan.db backups
```

## Daily targets

Borrowed from the earlier desktop version of this planner, which had the better
idea: judge a **day**, not a meal. Each day is measured against a ceiling to
stay under and floors to get past.

```
kcal      1938 / 2000     62 to spare
protein    122 / 140      18 short
fibre       33 / 25       met
```

Set the three numbers once at the top of the week; every day is then scored
against them and "Days that work" counts how many pass all three. This is much
closer to how people eat than hitting an exact figure at every meal.

Meals can be **switched off** without deleting them -- a day you are eating out
still has a plan -- and each carries a serving multiplier. A switched-off meal
counts for neither the daily totals nor the shopping list.

## Swaps

`GET /api/swaps?food=...` answers "what else could go in, and what would it
cost me". Alternatives are same-role only, sorted by how little they disturb
the calories, and each carries the change per 100g plus its price from the
local catalogue:

```
Dried red lentils   for brown rice   -9 kcal   +17.5g protein   +27.6g fibre
Firm tofu           for chicken     -21 kcal   -16.0g protein   $5.56/kg
```

These are derived from the ingredient table rather than hand-written, so they
stay correct as ingredients are added.

## Undo

Plans are saved as a whole document -- ticking one item rewrites everything --
so a bug or a mis-click could previously destroy a week with no way back. That
happened during development, which is why this exists.

Every write snapshots the previous contents first. The last 20 versions are
kept, `Undo` in the week header restores the most recent, and undo is itself
undoable. `GET /api/plans/{id}/history` lists what is available with a count of
what each version held.

The fault that prompted it: normalising a week to seven days *replaced* the
whole array whenever its length differed, discarding every planned meal, and
the next save made that permanent. It now pads and preserves, and folds any
extra days onto the last rather than dropping them.

## Barcode scanning

The **Scan a barcode** button on Find food opens the camera and reads the code,
then answers from three places in order:

1. **The local catalogue** -- instant, and works while a store is blocking us.
2. **Woolworths.** Their search takes a barcode directly and returns the exact
   product with its current price.
3. **Open Food Facts.** An openly licensed database of packaged food. No price,
   but usually the nutrition panel -- the part a supermarket listing lacks.

One scan therefore gives both:

```
Woolworths Full Cream Milk 3L        $5.16 / 3000g   $1.72/kg
per 100g   63.2 kcal  3.3g protein  4.8g carb  3.4g fat
```

Anything scanned is stored with its barcode, so scanning the same tin again
costs nothing. **Add to shopping list** puts it straight on the list with its
pack size and price.

Uses the browser's own `BarcodeDetector`, so nothing is downloaded and no
library is involved. That exists in Chrome on Android; elsewhere the sheet
offers a box to type the number into instead. The camera needs **https** --
browsers refuse it otherwise, localhost excepted.

## An Android app

The web app is already installable: on Android, Chrome offers **Install** and
it lands in the app drawer, full screen, updating whenever you publish because
the content is served rather than bundled.

For a real APK -- one that installs like any other app and can be sideloaded --
`scripts/build_android.sh` builds a **Trusted Web Activity** with Bubblewrap:

```bash
bash scripts/build_android.sh https://your-app-address
adb install -r android/app-release-signed.apk
```

The shell is a thin wrapper around the site, so **updates still arrive by
publishing the web app**. The APK only needs rebuilding if the name, icon or
address changes.

### It needs https first

Android refuses to build a TWA over plain http, because the app cannot
otherwise prove the site belongs to whoever signed it. Two things are required:

* **An https address.** Tailscale gives one free with a real certificate, but
  TLS certificates must be switched on for the tailnet first -- the admin
  console, DNS page, *HTTPS Certificates*. Without it `tailscale cert` answers
  *"your Tailscale account does not support getting TLS certs"*. Then:

  ```bash
  tailscale serve --bg --https=443 http://127.0.0.1:8000
  ```

* **The app's fingerprint on the server.** The build script prints it; put it in
  `.env` as `TWA_FINGERPRINT` and restart. The server publishes it at
  `/.well-known/assetlinks.json`, which is what removes the browser bar from
  the top of the app.

Keep `android.keystore` and its password. Losing them means a later build can
only replace the app, never update it.

## The Android app, as built

Built and installed on 31 Aug 2026. What it took, in case it needs doing again:

| Step | Detail |
|---|---|
| HTTPS | `tailscale serve --bg --https=443 http://127.0.0.1:8000` |
| Address | `https://sudo-kun.tail696f09.ts.net` |
| Package | `au.com.chronox.shelfplan`, version 1.0.0 |
| Signing | `android/android.keystore`, alias `android` |

Three things blocked the first attempt, all fixed:

* **Bubblewrap needs JDK 17**, not 21. Installed alongside; the JDK it uses is
  set in `~/.bubblewrap/config.json`, independently of `JAVA_HOME`.
* **It looks for `tools` or `bin` at the SDK root.** Modern SDKs put the
  command-line tools in `cmdline-tools/latest`, so a directory junction
  (`mklink /J`) at `<sdk>/tools` satisfies the check without disturbing the
  real layout.
* **`gradlew.bat` is invoked without a path prefix**, which Windows will not
  resolve. Running `./gradlew.bat assembleRelease` directly works, then align
  and sign with `zipalign` and `apksigner`.

`local.properties` needs forward slashes (`sdk.dir=E:/dev/android-sdk`);
backslashes are escape characters in a Java properties file and produce a
misleading "filename, directory name, or volume label syntax is incorrect".

### It still updates itself

The APK is a shell around the served site, so publishing the web app updates
the app. Rebuild it only when the name, icon, package or address changes.

### Keep the keystore

`android/android.keystore` is gitignored, as it must be. Back it up somewhere
safe: without it a later build can only *replace* the app, never update it.

### A caveat about tailnet addresses

Android's automatic link verification is done by Google's servers, which cannot
reach a tailnet-only hostname, so system-level domain verification will not
complete. Chrome performs its own asset-links check from the device, which
can reach it -- so the app still runs without a browser bar. On a publicly
resolvable domain both checks pass.

## A note on rate limiting behind a proxy

Tailscale's proxy rewrites `X-Forwarded-For` to the **server's own** tailnet
address rather than the caller's, so with `--proxy-headers` every device
collapses onto one key. A per-IP limit then silently becomes a limit shared by
everyone, and the first person to fumble a password reset locks out the rest.

The fix is to key on identity rather than address. Tailscale passes the
signed-in user as `Tailscale-User-Login`, which is both correct and more useful
than an IP:

```
tailscale-user-login: someone@example.com   ->   key "ts:someone@example.com"
```

That header is used **only** as a rate-limit key, never for authentication. It
can be forged by anyone able to reach the port directly, which would let them
dodge their own limit -- an annoyance, not a way in. Authentication remains the
signed session cookie and nothing else.

The limits themselves were also far too tight for a household: three password
resets an hour is fewer than most people take to work out what they are doing.
They now default to 10 per account and 20 per address per hour, and a refusal
says "try again in 58 minutes" rather than "3541 seconds".

Counters live in the serving process, so `docker compose exec ... reset_all()`
does nothing -- that starts a *separate* process. Restarting the container is
what clears them.

## When the stores block you

Both supermarkets block on request volume, and the block lands on your
**address** -- so it takes out everyone behind that connection, not just the
process that earned it.

* **Coles** answers with an Imperva JavaScript challenge (`_Incapsula_Resource`
  in a short body). Passing it means executing their script to earn a clearance
  cookie, which is bot-protection evasion rather than an integration, so this
  reports the block instead of working around it.
* **Woolworths** answers `403 Access Denied` from Akamai. In practice this is
  almost always the *address*, not the request rate: a VPN exit node is a
  datacenter IP, and Akamai refuses those on sight. Turning the VPN off fixed
  it immediately during testing. Genuine volume blocks do happen too and lift
  after a few hours.

Requests are therefore paced deliberately: **2.5s minimum between Woolworths
requests**, 1.8s for Coles, one at a time, with a circuit breaker that stops
calling a store that is refusing and a shared cache so repeat lookups cost
nothing. The background top-up runs at **one request every five minutes**.

The seeding script defaults to **6 seconds between terms** rather than the
1.2s it started at. That pace was never proven to cause a block -- a VPN turned
out to be the culprit -- but a full run at 1.2s does look like a crawler, and
the slower default costs nothing when the job has all day.

**If prices stop working, check for a VPN first.** It is by far the most common
cause, and it is instant to rule out.

**None of this stops the app working.** Find food reads the local catalogue, so
searching, prices and the shopping list all keep working from what has already
been indexed; only a live refresh fails, and it says so rather than showing
blank cells.

## Matching an ingredient to a product

Two faults, both found by using it:

**"Capsicum, raw" matched "Tomato and Red Capsicum Relish".** A relish is not a
near miss for a vegetable, it is a different item -- but the words overlap
almost entirely. Words marking a *prepared form* (relish, chutney, sauce,
paste, pickled, powder, juice, and so on) now count heavily against a candidate
unless the request asked for one.

**"Polenta" matched "Instant Polenta" and "Broccoli" matched "Frozen Carrot
Cauliflower & Broccoli".** The score only measured how many *wanted* words
appeared, so extra words in the product name cost nothing and pack size then
decided -- which is how a bag of mixed vegetables wins a search for broccoli.
Matching is now the harmonic mean of both directions: everything asked for is
present, **and little else is**. Plain beats instant, and single beats mixed.

```
Capsicum, raw   ->  Red Capsicum each
Polenta, dry    ->  La Gina Polenta Corn Meal 500g
Broccoli, raw   ->  Fresh Broccoli each
```

## Adding something should finish the job

Scanning a barcode and adding it used to leave a blank row until the next price
refresh, which read as broken. Items added from the catalogue always carried
their price; items known only to Open Food Facts -- anything Woolworths does
not stock -- did not.

Adding now prices the line straight away whichever route it came in by, and a
line that genuinely has no price says "no price yet" with a **set** button,
rather than showing a dash and leaving you to guess what to do.

## Scanning a trolley, not a tin

The scanner worked, but it asked too much: hold the phone still, wait, then tap
to add. Three faults, all fixable:

* **The camera was left to guess.** The stream asked for 1280 wide and nothing
  else. A barcode is thin black lines, and at that width the bars of a
  supermarket EAN blur into grey unless the phone is close and steady. It now
  asks for full HD and, where the camera offers it, continuous focus and
  exposure -- the other half of why it had to be held still.
* **It looked ten times a second at most.** Detection ran on a 250ms timer.
  It now runs every 90ms and skips frames only while a lookup is in flight.
  A code counts once two readings agree, which at that rate is under a fifth
  of a second: fast enough to feel instant, strict enough that a barcode caught
  edge-on cannot add the wrong tin.
* **Every item needed a tap.** With **Add as I scan** on -- the default -- a
  scan goes straight onto the list and the camera keeps running, so a trolley
  is scanned in one pass. Each item appears in a running list inside the sheet
  with a **remove** beside it, and the same barcode read again within a few
  seconds is the camera not having moved rather than a second jar. Turn the
  toggle off to get the old confirm-each-one behaviour back.

The frame flashes on a read, so a scan is visibly a scan on a phone with
vibration switched off, and there is a **Light** button where the camera has a
torch.

## When two products are equally right

"Polenta" describes *La Gina Polenta Corn Meal 500g* and *Marco Polo Polenta
750g* exactly as well. Both are polenta; everything else in either name is
brand and packaging, so no amount of reading the words separates them -- and
the order the store happened to list them in was quietly deciding, which is how
a search for polenta settled on the dearer corn meal.

This is a price tool. Where two candidates are equally the right thing, the
cheaper kilo now wins.

```
Polenta, dry           ->  Marco Polo Polenta 750g          $4.31/kg
Extra virgin olive oil ->  Moro Primero Olive Oil 1L        $13.50
```

## An ingredient is not a sandwich filling

Searching Woolworths for "chicken breast" and taking the best name match gave
*Primo Chicken Breast Sliced 80g* -- deli meat at $49/kg -- ahead of the kilo of
fillets the plan actually buys. Four separate faults, each real:

* **Pack size was gated behind the name score.** It only applied to candidates
  scoring 0.5 or better, and the shortest name always scores best, so the only
  product it ever reached was the 80g packet. Every pack that matched the kilo
  wanted scored below the gate and got nothing for it. Pack size now counts in
  both directions and is never gated.
* **Store-brand blurb was punishing.** "Woolworths RSPCA Approved" is three
  words of provenance and no food, and measuring how much of a name is on-topic
  scored it below the deli packet. Words that say who made it or how it was
  farmed are now ignored, as are pack sizes -- "1kg" was being read as a
  describing word.
* **Names were read as a bag of words.** Australian labels read brand, then
  food, then what was done to it: *La Gina | Polenta | Corn Meal*. Everything
  before the food is brand; everything after changes what it is. Trailing words
  now cost full price and leading ones a third, which separates plain polenta
  from polenta corn meal without throwing away every long store-brand name.
* **A mix read as the single thing.** "Kale & Baby Spinach" and "Carrot,
  Cauliflower & Broccoli" are mixtures, and the conjunction was invisible --
  "and" is a stopword. A product joining two foods now loses to the one.

Two more, found while testing: a search for zucchini returned a **cookbook**
called *Artichoke to Zucchini*, and mushrooms returned an **acrylic ornament**.
Both come from Woolworths' Everyday Market, a third-party marketplace served
through the same search and distinguishable by having no trading department at
all. Only real grocery lines are accepted now.

## Twenty dishes, not six

Six templates across ten themes meant every Irish recipe was a soup or a tray
bake. Fourteen more shapes -- stew, braise, chowder, skillet, bake, noodles,
fried rice, salad, wrap, skewers, pilaf, frittata, tagine, crumbed -- and
thirty-one more ingredients bring it to roughly **19,000 distinct dishes**,
1,400 to 3,000 per theme:

```
italian 1,660   japanese 3,066   chinese 3,030   thai 1,414   indian 1,791
greek 1,902     mexican 1,960    irish 1,930     middle-eastern 2,114
```

Each theme names its own dishes, so a Japanese rice bowl is a donburi, a
crumbed cutlet is a katsu, and a Greek skewer is souvlaki. `The recipe book`
on the Recipe builder tab pages through them.

## Pictures of what actually goes in

A generated recipe has no photograph, and inventing one would be a picture of a
dish nobody cooked. Showing the ingredients is both honest and more useful:
these are the real product shots already fetched for pricing, so a card shows
the chicken, the rice and the broccoli that are actually in it. 89 of the 90
ingredients have one; the rest fall back to a lettered tile.

## Planning the whole week

The planner has existed since daily targets went in, and there was no way to
ask for it from the page -- which is a feature that may as well not exist.
**Plan it for me** on the Week tab takes a calorie ceiling and protein and
fibre floors and fills seven days.

It no longer requires a stocked library either. Where there are not enough
saved dishes it composes them to the same targets and saves them, so what was
planned is a real recipe to rate, cook or delete.

Getting seven days out of seven to meet the targets took three fixes. Dividing
the ceiling evenly between meals left the packer no room, so it now aims under
the ceiling and over the floors. Building exactly enough dishes meant the last
days took whatever was left, so it builds a few spare. And every day came in on
calories and protein but short on fibre, because nothing was ever told the
fibre floor -- now that it is, the solver answers it the way a person would, by
serving more vegetables and by choosing one that can carry it. A tomato is
1.2g of fibre per 100g; no sane portion of it reaches 30g a day.

## Breakfast, lunch and dinner

A day was three interchangeable slots filled by whatever fit the numbers, which
is how the planner came to suggest chicken breast ragu at seven in the morning.
The numbers were right and the plan was useless.

Every dish shape now says when it belongs, and six breakfast shapes were added
-- porridge, a yoghurt bowl, a smoothie, eggs on toast, shakshuka, a breakfast
hash -- along with the ingredients they need. A day is planned as a breakfast,
then a lunch, then a dinner, each drawn only from dishes that belong there.

Sweet breakfasts are fenced off in a way the savoury ones are not. An
ingredient with no stated preference works anywhere in its role, which is
right for a vegetable in a stir-fry and puts broccoli in the porridge; porridge,
smoothies and yoghurt bowls take only what names them. A shakshuka wants
ordinary vegetables, so it is deliberately not on that list.

Two shapes were quietly wrong and are fixed with it: a frittata was inheriting
every base a rice bowl allows, and a wrap was doing the same -- which is where
"turkey mince wraps on egg noodles" came from.

## Vegan and keto

Vegan already worked; it simply was not offered everywhere it should have been.
It is now on the builder, the book and the week planner, along with keto.

Keto is decided by the numbers already recorded rather than a hand-kept list.
The measure is **net** carbohydrate -- what is left after the fibre -- because
that is what the diet counts, and counting the total gets it wrong in both
directions: it throws out broccoli at 7g and lets carrot in at 9.6g, when after
fibre they are 4.4g and 6.8g. Ingredients up to 6g per 100g qualify, and
because a plate of qualifying parts can still add up past the limit, a listed
keto dish is also checked to come in under 20g a serving.

Three low-carb bases were added so a keto dish has something to sit on:
cauliflower rice, zucchini noodles and konjac noodles.

## The book's "See it" did nothing

A saved recipe carries `notes` as the one line you typed. A freshly built one
carries the builder's *list* of what it could not quite hit. The card called
`.trim()` on it, which throws on a list, so the click died silently. It now
takes either.

## Reading it in an aisle

The type was set for a monitor at arm's length: 13px secondary text, and most
of this app is secondary text. Everything steps up, and the item name on the
shopping list -- the thing you are actually scanning for one-handed in an
aisle -- is now the largest thing on its row.

The palette moved off cold grey onto warm paper so the cards have something to
lift from, and the nine tabs became pills, which read as separate things and
take a thumb better than a strip of underlined labels.

## Keeping a list

**Save this list** keeps a named copy, and **Clear list** empties it. Saved
lists live in the plan itself rather than in one browser, so they survive an
export and travel to another device. Restoring merges prices rather than
replacing them -- a price recorded since is newer than the one saved with the
list. Both are undoable from the Data tab.

## Sixty rules that never applied

The ingredient photographs, the recipe book grid, the scanner's flash, the week
planner's day list -- none of them had ever been seen. An earlier edit of mine
had left an `@media (max-width:560px){` open, and everything written after it
was nested inside a phone-width media query. On a phone it was hidden behind
whatever came next; on anything wider it simply did not exist.

Nothing failed. CSS has no way to fail: an unclosed block swallows what follows
and the page renders, quietly missing its design. The stylesheet had 227 usable
rules where it should have had 277.

The runaway had been closed by a stray brace sixty lines further on -- attached
to `.thumb{...}}`, a rule that only worked *because* of the runaway. Both are
fixed, and `scripts/test_stylesheet.py` now checks the braces balance and that
every rule the page depends on is reachable at the top level.

## Breakfast, when the library already had recipes

The planner tops the library up before planning, and it counted recipes rather
than *breakfasts*. A library of a dozen dinners is twelve recipes, so the count
said "enough", nothing was composed, and the morning was left empty. It now
stocks each sitting separately.

That exposed a second miscount. Most savoury dishes suit lunch and dinner
alike, so one pool covers both: four dishes repeating three times each is
twelve servings against the fourteen a week of lunches and dinners wants, and
the seventh day ran out. The requirement now accounts for a pool serving two
sittings.

## "0 of 17 in the basket"

Ticking an item off wrote the new count into `document.querySelector('.card .sub')`
-- and the sign-in card stays in the document after you sign in, so the first
`.card .sub` on the page is *its* subtitle. The count was going into a hidden
element while the real one sat at zero. It has its own id now, updates before
the save rather than after it, and says so if the save fails.

## Clearing the week looked like it did nothing

It did work: the seven day cards emptied. But the planner's report -- the list
of what it had planned, Monday to Sunday -- stayed on screen underneath,
listing every meal. Clearing and undo now drop the report, it is headed "What
it planned" so it reads as a record rather than as the week, and it can be
dismissed.

## Prices you can find something in

The list was one long scroll in insertion order. It can now be searched by
food, product or store, and sorted six ways -- alphabetical by default, because
a price list is something you look a thing up in.

Judging a price needed history, and with one reading everything said "no
history yet". The shelf itself knows: `wasPrice` is now carried through from
the store and recorded with each reading, so a first reading can still say
**on special, 33% off its usual $4.50**.

## Written-your-own recipes read 0 kcal

Nutrition came only from Open Food Facts, which answers to a barcode and often
has never seen an Australian store line. When it had nothing, every figure was
zero, the recipe went into the week reading 0 kcal, and nothing on screen said
why.

A store name still describes a food, so it now falls back to matching the
ingredient table: *Woolworths RSPCA Approved Chicken Breast Fillet 1kg* is
chicken breast. Every line says where its figures came from -- from the label,
estimated, entered by hand, or **no nutrition** -- and the card warns when the
total is missing something. A weak match is refused rather than guessed: at the
first threshold a Cadbury Dairy Milk block matched "Milk, skim" and would have
been presented as 35 kcal.

Saved own-recipes now keep their product photographs, which is why they had
none in the library: the photo map only knows the builder's own ingredient
names, and a store product is not one of them.

## Imported recipes keep their own measures

Importing the RecipeTin Eats soda bread turned "2 cups buttermilk" into "455 g
buttermilk" and "1 1/2 tsp baking soda" into nothing at all. The rule was "if
we can work out the grams, say grams" -- and the grams are *our* conversion, so
the numbers quietly disagreed with the page they came from.

Cups and spoons are how recipes are written in both systems, so they are now
scaled rather than converted, and written as a cook writes them:

```
2 cups white flour            about 265 g
1 3/4 cups wholemeal flour    about 230 g
1 1/2 tsp baking soda
2 cups buttermilk             about 500 ml
```

The weight or volume is offered alongside, in millilitres for a liquid, and the
page's own wording is shown against any line that scaling has had to change.

## A library you can search

Search by name or by ingredient -- "what can I do with the mince in the fridge"
is the question a library actually gets asked -- filter by meal and by kind,
and sort by rating, name, times cooked, calories or protein.

## A week that costs $500

The planner chose meals on nutrition alone, and maximised variety while it was
at it -- which is the most expensive thing it could possibly do. Every new dish
brings new ingredients, and a shopping list is bought in whole packs. Twenty
different dinners is twenty packs of meat.

The plan this app was built to replace did the opposite. The same protein
overnight oats every morning, the same beef chilli twice, about fifteen
distinct ingredients across the week, and it cleared 150g of protein and 25g of
fibre a day for under a hundred dollars. Meal prep is repetitive on purpose,
and the repetition is most of what makes it affordable.

Three things were missing:

**The planner could not see the trolley.** It now costs a candidate by its
*marginal* price -- the extra packs it forces, given what is already being
bought. A second chicken dish that stays inside the kilo already on the list is
nearly free; one unfamiliar ingredient costs a whole jar. This is invisible to
any scoring that looks at a recipe on its own.

**The builder could not see prices at all.** It can now, and what it weighs is
not what a serving costs but **what its protein costs**. Penalising the plain
price pushed it onto beans and grains -- cheap, and nowhere near 150g a day. A
$4 serving carrying 55g of protein is better value than a $2 one carrying 20g,
and that is the choice the old plan made over and over: whey, yoghurt, chicken
breast, lean mince.

**Variety was the strongest term in the score.** `max_repeats` now defaults to
five rather than three, and repeating a dish costs much less than it did.

On a fresh library, planning to a $110 budget now returns **all seven days on
target -- 1827 kcal, 160g protein, 32g fibre -- for $162 at the till**.

### Two numbers, not one

You pay for whole packs, so the till total is what leaves your account. But a
$38 tub of whey that lasts two months is not a weekly food cost, and a plan
judged on the till total alone looks far more expensive than the eating is. The
planner now reports both, and names what is mostly left over:

```
At the till        $161.57
Eaten this week     $82.37
Pack you keep       $79.20
Mostly left over: whey protein $38.02 (22% used) · olive oil $19.00 (21% used)
```

### What a budget cannot fix

The planner can only choose from the recipes you have saved. A library built
before budgets existed stays expensive no matter what number you type, because
the top-up only composes new dishes when a *sitting* is short, not when the
week is dear. It now tries a cheaper round and re-plans -- keeping the result
only if it is both cheaper and no worse on target -- and says plainly when the
saved recipes are the reason it cannot get there.

A rejected attempt no longer leaves its dishes behind, either. It used to save
them anyway, so the next plan picked them up and came out worse: a failed
experiment quietly poisoning the thing it was testing.

## A day you can read

The old plan put the whole day on the page -- the day's totals, then each meal
named, its ingredients with their grams, and what that meal came to. You could
see what Tuesday was by looking at Tuesday. Here you got a name and a calorie
figure, and everything else was a click away.

Each day now carries its full macro line, and each meal shows its own energy,
protein and fibre with the ingredient list underneath at the servings planned.
**Show ingredients** turns the detail off for a tighter view, and remembers.

## Two bugs found on the way

`budget` was already the name of a local variable in the planner -- the calorie
allowance for one sitting -- so the money budget was overwritten on the first
loop and reported back as a calorie figure in dollars.

A planned meal whose recipe had been deleted rendered as nothing at all, so a
day silently came up a meal short with no way to tell why. It now says so.

## Forty-two bags of spinach

The shopping list multiplied by the batch size *as well as* the servings eaten:

```js
line.grams += i.gramsPerServing * m.servings * r.servings;
```

`m.servings` is already how many servings that meal takes. Multiplying by the
recipe's batch size on top bought four servings' worth of everything for every
serving planned -- **four times the food**, which is where forty-two bags of
spinach and the five-hundred-dollar week came from, and why the planner's own
estimate ($143) disagreed so wildly with the list.

The same week now builds a fifteen-item list totalling **$150**, and the two
figures agree. The list also opens with prices already in it, seeded from the
catalogue table the planner worked the budget out from, instead of $0.00 and a
column of dashes.

## Landing on the calorie target

Days stopped wherever whole servings happened to stop -- routinely a hundred or
more short of the ceiling, which across a week is most of a day's food never
eaten. Servings now move in tenths, and each day is filled toward the ceiling
without crossing it, preferring whichever meal still closes an open floor:

```
day 0   1857 kcal   168g protein   29g fibre    servings [1, 1.1, 1]
day 1   1896 kcal   173g protein   35g fibre    servings [1, 1, 1.1]
day 2   1896 kcal   173g protein   35g fibre
...
week average 1887 kcal/day, every day on target, $143 at the till
```

Tenths are not fussy: 1.3 servings of the chicken bowl is 260g of chicken,
which is the same thing the plan this replaced did when it wrote grams instead
of portions.

## One day at a time

Seven days side by side is a lot to take in and, on a phone, a lot to scroll
past. **One day** shows a single day with arrows either side, opening on today,
and remembers which view you left it in.

## A special that looks like one

"on special" as a word among other words is the easiest thing on a row to miss,
and catching the prices that have moved is most of why anyone reads a price
list. A discounted line now carries a red **SPECIAL** flag, a tinted row, the
price in red with the old price struck through above it, and the percentage
off.

## The report is not the week

Adding a meal by hand updated the day, but the planner's report above it went
on describing the week it had planned -- so the totals appeared not to change.
Any hand edit now retires the report, the same way clearing and undo already
did. A meal added by hand also lands in whichever sitting the day is still
missing rather than showing up unlabelled.

## Clearing the library

**Delete all** in the recipe library, which deletes *what is on screen* rather
than everything unconditionally. The filters are right there, so wanting rid of
just the expensive ones, or just the breakfasts, is a filter and one button
instead of twenty separate confirmations. The button says which it is --
"Delete all 9" or "Delete these 3" -- and the confirmation repeats the count.

Both the page and the button read the same `libShown()`, because a button
saying "delete these 6" has to mean the same six on the screen; two copies of
that filtering could drift apart, and the way you would find out is by losing
recipes.

The request names the ids outright rather than meaning "everything", the server
ignores any that are not yours or no longer exist, and an empty list is
refused. Recipes are not covered by the plan's undo, so the confirmation says
plainly that this one cannot be taken back and that days still using them will
say the recipe is missing.

## Swapping the product behind a line

The matcher is right most of the time and wrong some of the time, and when it
was wrong the only recourse was to correct the price by hand -- which fixes the
number and leaves the line still pointing at the wrong tin, ready to be
overwritten on the next refresh.

**swap** on any shopping row opens the alternatives, ranked the way the
resolver ranks them, each with its pack size, price per kilo and shelf price,
and specials flagged. There is a search box for something else entirely, and a
button to ask the store for anything the catalogue has not seen.

Choosing one takes its price, pack size, picture and link with it, and works
the packs needed out again -- keeping the old count would price the new tin by
the old tin's arithmetic.

### And it stays swapped

A choice is recorded against the line as a stockcode plus the name that was
picked. A price refresh re-prices *that* product rather than re-resolving,
because re-resolving would hand the line straight back to the match that was
just rejected: swapping would appear to work and then quietly undo itself an
hour later.

A line only counts as chosen when somebody chose it. Matching on stockcode
alone would also catch the lines the resolver filled in itself, and those
should carry on being re-matched as prices and stock move.

## Prices that keep themselves up to date

They did not. Nothing was scheduled, so a plan's price history only moved when
somebody pressed **Refresh prices** — which makes the history sparse and the
"cheapest yet" verdict weak. A run of readings taken whenever a person happened
to open the page says much less than one reading a week taken on the same day.

Woolworths and Coles both start their new specials on a **Wednesday**, so that
is the day worth reading. `webapp/autoprice.py` walks every plan once a week,
early on Wednesday, and appends that day's price to any line not read in the
last five days. The Prices tab says when it last ran and when it next will, and
has a **Check now** button.

Two rules keep it from becoming a nuisance:

* It reads the **catalogue**, never the shops — nothing in it makes an outbound
  request. Keeping the catalogue fresh is the trickle job's business, and that
  is already paced for it.
* A line you pinned by hand keeps the product you chose, exactly as a manual
  refresh does. A shaky match is skipped rather than written: better a gap in
  the history than a wrong reading in it.

`AUTO_PRICE=0` turns it off; `AUTO_PRICE_DAY` and `AUTO_PRICE_HOUR` move it.

## Where a recipe came from

Three ways one gets into the library, and they are worth telling apart: the
ones **you wrote**, the ones **from the web**, and the ones the builder made up
to hit a number. A "Where from" filter and a tag on the card.

## The book, and the plans

The recipe book has moved to the top of the **Recipes** tab, which is where you
go looking for a recipe — it was filed under the builder, which is where you go
to describe one.

Plans can be renamed and deleted. Both endpoints already existed; there was
simply no way to reach them, so a plan once made was permanent. Deleting says
what goes with it — the week, the shopping list, the saved lists, the price
history — because none of that is covered by Undo, which only reaches back
through versions of a plan that still exists.

## Metric and imperial, doing something

The switch appeared dead, and on a recipe written entirely in cups and spoons
it was: the previous fix stopped converting them at all, on the grounds that
both systems use the same words.

They do not use the same sizes. An Australian tablespoon is 20ml and holds four
teaspoons; an American one is 15ml and holds three. Ignoring that left the
switch visibly doing nothing *and* quietly wrong by a quarter on anything
raised with bicarbonate. Quantities are read as Australian -- which is what
this app is for -- and converted on the way out:

```
metric     2 cups white flour        2 1/2 tbsp extra flour
imperial   2 1/8 cups white flour    3 1/3 tbsp extra flour
```

## The imported photograph

Blocked by this app's own content security policy, which allows images from
this server and the two supermarket CDNs and nothing else. Widening that to
"any https host" would have worked and would also mean every recipe site you
look at gets told your address.

`webapp/imageproxy.py` fetches it server-side instead: https only, public
addresses only -- checked after DNS resolution and again after any redirect,
because a hostname can resolve to something on your own network and this runs
on home networks behind Tailscale -- with a 4MB cap, a short timeout and a
day's caching. Signed in only, so it is not an open proxy.

The picture then still did not appear, for a second reason: `loading="lazy"`
inside the scrolling panel never triggered, leaving an element with a valid
src and an empty `currentSrc`. The one photograph at the top of a card somebody
has chosen to look at does not need deferring.

Saved imported recipes show their photograph too, which they never did.

## A day has a shape

The builder defaulted to 600 kcal a serving, which is a number for no meal in
particular. Splitting a day evenly is the arithmetic answer and not how anyone
eats -- breakfast is smaller than dinner in every country that has all three --
but somebody batch-cooking one dish to eat three times genuinely does want
three identical portions.

So both, and the choice is stated rather than assumed: **breakfast smaller than
dinner** (25 / 35 / 40) or **every meal the same size**. The planner builds
each sitting to its share, and the builder can size a single recipe for a named
sitting instead of a flat figure.

The day's numbers themselves come from a goal and a bodyweight rather than
being typed from nowhere -- losing fat, staying put, building muscle, training
hard -- stated the way the research states them, in grams per kilogram:

```
at 90kg    losing fat  2350 kcal  200g protein  33g fibre
           building    3400 kcal  180g protein  41g fibre
```

Published ranges, not advice, and the page says so.

## Swapping a planned meal

Removing a meal and adding another from the full list means doing the
arithmetic yourself -- you wanted something else for Tuesday, not something
that quietly costs the day forty grams of protein.

**swap** on a planned meal offers the library sorted by how close each dish is
to the one being replaced, restricted to that sitting, and says what the
difference would be: `+88 kcal +26g P +1g F`, or "much the same".

## Imperial that looks imperial

Switching systems moved the cups from 2 to 2 1/8 and stopped there, which is
true and reads as nothing happening. The reason was that the *equivalent*
alongside each line -- the "about 265 g" that is most of the useful information
-- stayed in grams whichever system was chosen.

It follows the system now, which is most of what the switch is for:

```
metric     2 cups white flour          about 265 g
imperial   2 1/8 cups white flour      about 9 1/3 oz
metric     2 cups buttermilk           about 500 ml
imperial   2 1/8 cups buttermilk       about 1 US pint
```

## Cards that end where they end

A CSS grid stretches every cell to the tallest in its row, so a short recipe
sitting beside a long one gained several hundred pixels of nothing beneath its
footer. Cards keep their own height now.

The tags under the title had no room above them and butted straight into the
header's rule, which is what made them look sliced off. And a card whose
ingredients have no photographs no longer shows a band of three big lettered
squares: they are not a picture of anything, and the card reads better without.

## Two packs of cauliflower

Nobody has ever picked up a one-kilogram pack of cauliflower. The `pack` figure
on an ingredient is a costing unit -- what a kilo of it costs -- and the
shopping list was printing it as a shopping instruction.

Twenty-four foods are now marked as sold by weight or by the each, and for
those the list says **how much** rather than **how many**:

```
Banana          1.1 kg          Cavendish Bananas each
Cabbage         2.1 kg          Green Cabbage Quarter each
Turkey mince    3.2 kg · 7 packs   Ingham's Turkey Mince 500g
```

The mince really does come in packs, so it still counts them.

## A picture of a cauliflower

Where the catalogue has no photograph -- a food nobody has searched for yet, or
one the store ships without an image -- the tile showed the food's first
letter, which is a picture of nothing. It now shows a glyph for what kind of
thing it is: 🥦 for the cauliflower, 🍌 for the banana, 🍗 for the chicken.
Longest match first, so "sweet potato" is not read as "potato".

Nothing is fetched to do this, which is why it could be done for every
ingredient at once rather than only the ones the catalogue happens to know.

## Cards that are roughly the same size

Folding the method away in the library took the spread from 545–1038px to
608–649px. It is not what you are scanning for -- you are looking for something
to cook, and you read the method once you have chosen -- so it sits behind a
heading that says how many steps there are. Where a single recipe *is* the
page, it stays open.

## A tag wearing two hats

The meal-of-the-day tag was `class="tag meal meal-breakfast"`, and `.meal` was
already the class for a shopping-list row. The tag quietly inherited that row's
`padding: 6px 0` and its bottom border, which is what squashed the pills flat
against their text. Renamed to `when`, and the stylesheet guard now checks for
it so the collision cannot come back unnoticed.

## Pictures that never arrived

Every thumbnail on the shopping list carried `loading="lazy"`, on the reasoning
that a catalogue page can hold sixty of them and the store CDNs are slow. Inside
these scrolling panels Chrome never decides they are near enough to load, so
they sat for ever with a valid `src` and an empty `currentSrc`. The same fault
had already been found on the imported recipe photograph; it was everywhere
else too. A picture that never arrives is worth less than a slow one.

## A picture that belonged to the wrong product

The broccoli line showed a bag of Birds Eye frozen mixed vegetables long after
the match itself had been corrected, because a refresh only ever *filled in* a
missing picture:

```python
if result.get("image") and not shop.get(food, {}).get("image"):
```

So the first picture a line was given was the one it kept. Pictures and store
links are now replaced along with the price they came with, and the price table
returns the image belonging to whichever product it actually priced -- it had
stopped returning one at all, which is why nothing corrected itself.

## "Polenta 500g" is a filter, not a search

The catalogue matches on every word, so an ingredient whose query carried a
pack size could only ever match products whose label happened to repeat it.
"Polenta 500g" excluded the 750g bag -- and because two 500g products *did*
match, the widening fallback never fired and the better, cheaper pack was never
a candidate. The size is stripped before the search now, not only when the
search finds nothing.

Widening it let tins in, which is how a recipe wanting cherry tomatoes was
offered a tin of Mutti. Two things stop that: a candidate that is tinned,
frozen or dried loses to a fresh one unless the plan asked for it kept that
way; and where the store has said which department a product sits in, a produce
ingredient is matched only against Fruit & Veg. `Mutti Whole Cherry Tomatoes`
does not say "tinned" anywhere in its name, and the department is the only
thing that reliably knows.

## The Pack column

Removed. It said `1000 g` for a cauliflower -- a costing unit, in a column
headed as though it were a shelf pack -- while the product description beside
it already gives the real pack size and the line underneath already says how
much to buy. Three places for two facts, one of them wrong.

## The plan header on a phone

A brand, a picker with a 180px floor and four buttons in one wrapping flex row
made a different ragged shape at every width. Below 700px the picker takes a
row of its own and its buttons share it evenly.

## One product, another price, a third link

The broccoli line still opened a bag of Birds Eye frozen mixed vegetables after
the picture had been corrected, because the picture was only ever half the
line. A shopping row draws its name, price and link from the stored **price
reading**, and that reading still held the old match: `Birds Eye Frozen Carrot
Cauliflower & Broccoli, $6.50, /productdetails/217969`.

Two things were wrong. The price table returned the chosen product's image but
the *resolver's* URL, so where a cheaper equivalent won on price the link stayed
behind — one product shown, another costed, a third linked. The link now moves
with the picture and the price, and the stockcode with it.

And a reading matched to the wrong product is not an observation of that food
at all. Leaving it in the history is worse than useless: it feeds the trend line
and the "cheapest yet" verdict with the price of something else. Readings whose
matched product the current matcher rejects — a mixture, a prepared form, a
contradicted qualifier, tinned where fresh was wanted — are dropped rather than
kept as data.

## What a review of the day's work found

Reviewing for the *classes* of bug already found, rather than for new ones,
turned up five more instances of them.

**Password reset was unreachable.** The reset form existed, the endpoint
worked, the email sent a correct link — and `boot()` never looked for the
token, so every reset link showed the sign-in screen instead. The form and the
route to it had been built at different times and never joined up.

**The pack-size fix had gone into one caller of four.** Stripping the size out
of a catalogue query landed in the price table only. The weekly check and the
swap sheet still narrowed on it, so the Wednesday run would have quietly
re-matched polenta to the dearer corn meal every week — a fix applied where the
symptom was noticed rather than where the cause was. The produce-department
preference had the same shape: one caller.

All ingredient lookups now go through `pricing.candidates_for`. Exactly one
direct `catalogue_search` remains, in the catalogue search box, where a query
is a query. A test asserts that count so they cannot drift apart again.

**Ingredient swaps took the cheapest per kilo out of a raw search**, with no
check that the cheapest thing was the right food and the pack size still
narrowing what it could find.

**The weekly check refused to price anything sold by the each.** It skipped any
match flagged `needs_review`, and "sold per-each, no weight basis" is one of
those flags — so broccoli, bananas, cauliflower and every loose vegetable would
never have been priced at all. A doubtful *product* and a product with no
weight to divide by are different things, and the resolver now says which is
which.

`scripts/test_review.py` keeps all of it.
