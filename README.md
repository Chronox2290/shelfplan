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
