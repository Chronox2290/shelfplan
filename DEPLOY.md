# Putting Shelf Plan online

The goal: send someone a link, they open it on a phone or laptop, add it to
their home screen, and it behaves like an app.

That needs one thing above all: **HTTPS on a real hostname.** Browsers refuse to
register a service worker over plain http (localhost excepted), and without the
worker there is no install prompt and no offline shell. Everything below is in
service of that.

---

## Option A -- Fly.io (fastest)

Deploys the existing `Dockerfile`, issues TLS automatically, and gives you a
`*.fly.dev` hostname. `fly.toml` is already in the repo.

```bash
# once
curl -L https://fly.io/install.sh | sh
fly auth login

fly launch --no-deploy --copy-config --name YOUR-APP
fly volumes create shelfplan_data --size 1 --region syd

fly secrets set \
  SESSION_SECRET="$(openssl rand -base64 48)" \
  SIGNUP_INVITE_CODE="$(openssl rand -hex 8)" \
  PUBLIC_URL="https://YOUR-APP.fly.dev"

fly deploy
fly secrets list          # confirm; values are write-only
```

`primary_region = "syd"` keeps supermarket lookups inside Australia. Change the
`app` name in `fly.toml` to match `YOUR-APP`.

`min_machines_running = 1` is deliberate: the Coles cache and the rate-limit
counters live in process, so a suspended machine loses both.

## Option B -- your own server, with a domain

Point an A record at the box, then:

```bash
cp .env.example .env
# fill in DOMAIN, EMAIL, SESSION_SECRET, SIGNUP_INVITE_CODE
docker compose -f docker-compose.prod.yml up -d
```

Caddy obtains and renews a Let's Encrypt certificate by itself. Only Caddy is
published on 80/443; the app listens on an internal network, so nothing reaches
it over plain http.

Hetzner's smallest instance (~€4/mo) is ample.

---

## Settings that matter once it is public

| Variable | Set it to | Why |
|---|---|---|
| `SESSION_SECRET` | a long random string, kept stable | signs session cookies; changing it signs everyone out |
| `PUBLIC_URL` | `https://your-host` | turns on HSTS and the http→https redirect |
| `COOKIE_SECURE` | `1` | without it the session cookie travels in clear |
| `SIGNUP_MODE` | `invite` (default) | otherwise anyone with the link can create an account |
| `SIGNUP_INVITE_CODE` | a random string | what you send along with the link |
| `DATABASE_URL` | leave as SQLite | fine for a household; Postgres is supported |

The app prints a warning at startup if `PUBLIC_URL` is set while
`COOKIE_SECURE` is off, if signup is open on a public host, or if
`SIGNUP_MODE=invite` has no code set (which would lock everyone out).

**`--proxy-headers` is already in the Dockerfile's `CMD`.** Both Fly and Caddy
terminate TLS and forward plain http internally, so without it the app would
think every request was insecure and redirect in a loop. It also gives the rate
limiter the real client address instead of the proxy's.

---

## Sharing it

Send two things: the URL, and the invite code.

- **Android / desktop Chrome or Edge** -- an **Install** button appears in the
  header. One tap and it lands in the app drawer or dock.
- **iPhone / iPad** -- Safari never fires the install event, so the button
  stays hidden by design. Share → *Add to Home Screen*.

Either way it opens fullscreen with no browser chrome, has its own icon, and
keeps them signed in for 30 days.

---

## What is protected, and what is not

Built in:

- Argon2id password hashing; signed http-only `SameSite=Lax` session cookies
- Per-IP **and** per-account login rate limits, both checked *before* the
  password is verified, so a flood never reaches the expensive hash. A correct
  password clears the counters, so ordinary typos cannot lock out the owner.
- Registration rate limiting and invite gating
- A cap on price refreshes per user per hour
- CSP, `X-Frame-Options: DENY`, `nosniff`, HSTS when public
- Per-user ownership checks; someone else's plan id returns 404, not 403

Still missing -- know these before sharing widely:

- **No password reset.** There is no recovery path: a forgotten password means a
  lost account. This is the biggest gap for non-technical users, and it needs an
  email sender before it can be fixed.
- **No email verification.** Anyone with the invite code can register any
  address, including one that is not theirs.
- **Rate-limit state is per process.** Correct for one container; run two and
  the effective limit doubles. Move it to Redis if you scale out.
- **Coles rate-limits your server's IP, shared across all users.** Several
  people refreshing prices will trip the interstitial sooner than one person
  would. The 30-minute cache is shared, which helps, and the app degrades to
  Woolworths-only rather than failing.

---

## Backups

Everything is in one SQLite file.

```bash
# Fly
fly ssh console -C "sqlite3 /data/shelfplan.db .dump" > backup.sql

# Docker
docker compose -f docker-compose.prod.yml exec shelfplan \
  python -c "import sqlite3,sys; [sys.stdout.write(l+'\n') for l in \
  sqlite3.connect('/app/data/shelfplan.db').iterdump()]" > backup.sql
```

Losing the volume loses every account and plan, so take one before upgrading.
