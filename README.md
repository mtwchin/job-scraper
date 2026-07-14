# Internship Radar 🛰️

Polls top tech companies' **official career APIs** every ~10 minutes and pings a
**Discord webhook** the moment a new **SWE/SDE internship or new-grad** role opens.
Tuned for **off-season** (fall/winter/spring) internships by default.

It runs free on **GitHub Actions** — no server, no laptop-on-required.

---

## How it works

```
companies.md  ──►  per-company adapter  ──►  filter (SWE + intern/new-grad)
                                                     │
            seen_jobs.json  ◄── dedup ──────────────┘
                                                     │
                                              Discord webhook 🚨
```

- **`companies.md`** is the source of truth: a markdown table of companies, the
  adapter to use, and its config. Edit this to add/remove companies.
- Each company is fetched independently — **one broken site never stops the run.**
- **`seen_jobs.json`** records every job already seen, so you only get pinged on
  genuinely new postings. On GitHub Actions it's committed back after each run.
- The **first run seeds quietly**: it records all currently-open roles and sends a
  single "I'm live" message instead of spamming you with hundreds of existing jobs.

### Supported adapters

| Adapter      | Platform                        | Config needed                         |
|--------------|---------------------------------|---------------------------------------|
| `greenhouse` | boards-api.greenhouse.io        | `token=<board_token>`                 |
| `lever`      | api.lever.co                    | `slug=<company_slug>`                 |
| `ashby`      | api.ashbyhq.com                 | `slug=<company_slug>`                 |
| `workday`    | *.myworkdayjobs.com             | `host=;tenant=;site=` (deep paginated) |
| `eightfold`  | *.eightfold.ai / careers hosts  | `host=;domain=`                       |
| `amazon`     | amazon.jobs                     | — (custom)                            |
| `google`     | google.com/about/careers        | — (custom, scrapes results page)      |
| `meta`       | metacareers.com GraphQL         | — (custom, **disabled**, doc_id rotates) |
| `microsoft`  | careers.microsoft.com           | — (custom, **disabled**, old API dead) |
| `apple`      | jobs.apple.com                  | — (custom, **disabled**, needs JS CSRF) |

Verified-working out of the box: **Amazon, Google, Netflix, Palantir, OpenAI,
Ramp, Notion, Plaid, Stripe, Databricks, Coinbase, Robinhood, Airbnb, Dropbox,
Reddit, Pinterest, DoorDash, Instacart, Lyft, Brex, Figma, Discord, Anthropic,
Scale AI, Cloudflare, Roblox, Block, Affirm, Asana, Samsara, Nvidia, Salesforce,
Adobe, PayPal**.

> **Meta / Microsoft / Apple** are coded but disabled — their public APIs are
> currently locked behind rotating tokens, dead endpoints, or JS-rendered CSRF.
> See "Adding & fixing companies" below to re-enable when you find a live endpoint.

---

## Setup (≈10 minutes)

### 1. Create the Discord webhook
In Discord: **Server Settings → Integrations → Webhooks → New Webhook**, pick the
channel you want notifications in, then **Copy Webhook URL**. It looks like
`https://discord.com/api/webhooks/123.../abc...`.

### 2. Test it locally first (optional but recommended)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Dry run — hits every API, prints what it WOULD send, sends nothing:
DRY_RUN=true .venv/bin/python -m jobscraper

# Real send to your Discord (delete seen_jobs.json first to force a fresh seed):
DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...' .venv/bin/python -m jobscraper
```

### 3. Push to GitHub
```bash
gh repo create internship-radar --private --source=. --remote=origin --push
# or create a repo in the UI and: git remote add origin <url> && git push -u origin main
```

### 4. Add the webhook as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- **Name:** `DISCORD_WEBHOOK_URL`
- **Value:** your webhook URL

(Or via CLI: `gh secret set DISCORD_WEBHOOK_URL`.)

### 5. Done
The workflow in `.github/workflows/scraper.yml` runs every 10 minutes. Trigger the
first run manually from the **Actions** tab → *internship-radar* → **Run workflow**
to confirm everything works. The first run sends one "I'm live" message and seeds
state; after that you only get pinged on new postings.

---

## Commands

Install once (`pip install -e .`) to get a `jobscraper` command, or use
`python -m jobscraper <cmd>`:

| Command | What it does |
|---------|--------------|
| `jobscraper run` | Fetch all companies (in parallel), filter, dedup, notify. The scheduled command. |
| `jobscraper list [--disabled]` | Show tracked companies and the adapter breakdown. |
| `jobscraper audit` | Freshness report — catch latency of past alerts (see below). |
| `jobscraper doctor` | Health-check every company: which can produce alerts, which are broken. |
| `jobscraper discover <name\|url>` | Detect a company's ATS config to add/fix it. |
| `jobscraper test-webhook` | Send a test message to confirm your Discord webhook works. |

**`doctor`** is the tool for "are all my companies actually working?" It flags
companies that fetch nothing (a broken token — can never alert), separately from
companies that fetch fine but happen to have no matching role open right now
(normal, especially off-season). Most runs alerting on few roles is expected: at
any moment only a handful of companies have a *fresh* (<24 h) US/CA SWE role.

Run fetches companies concurrently (`CONCURRENCY`, default 12), so ~136 companies
complete in ~25–30 s rather than minutes. Logs are structured (`LOG_LEVEL=DEBUG`
for per-company detail), and if a large share of companies error in one run
(`HEALTH_ALERT_THRESHOLD`) it posts a Discord heads-up so a systemic break — a
platform outage or a shipped bug — doesn't fail silently.

`pytest` covers the filter and config logic and runs in CI (`.github/workflows/
tests.yml`) on every push.

---

## Tuning

Set these as env vars (locally) or edit the `env:` block in the workflow:

| Variable            | Default            | Meaning                                            |
|---------------------|--------------------|----------------------------------------------------|
| `ROLE_TYPES`        | `intern,new_grad`  | Comma list; use `intern` only or `new_grad` only.  |
| `OFF_SEASON_ONLY`   | `false`            | `true` drops summer-only internships.              |
| `US_CANADA_ONLY`    | `true`             | `true` keeps only US/Canada roles.                 |
| `INCLUDE_UNKNOWN_LOCATIONS` | `true`     | Keep roles with no/ambiguous location.             |
| `STALE_POSTED_DAYS` | `21`               | Hide the "Posted" label when the board date is older (display only). |
| `DRY_RUN`           | `false`            | `true` = print only, never send/save.              |
| `SEED_QUIETLY`      | `true`             | `true` = first run seeds silently.                 |
| `MAX_NOTIFICATIONS_PER_RUN` | `60`       | Safety cap per run.                                |
| `CONCURRENCY`       | `12`               | Companies fetched in parallel.                     |
| `HEALTH_ALERT_THRESHOLD` | `0.25`        | Discord heads-up if this share of companies error. |
| `LOG_LEVEL`         | `INFO`             | `DEBUG` shows per-company fetch/error lines.        |
| `DISCORD_WEBHOOK_URL_ALL` | unset        | Second channel: every Simplify SWE role, any company. Unset = disabled. |
| `SIMPLIFY_ALL_ENABLED` | `true`          | Master switch for the all-companies feed (still needs `DISCORD_WEBHOOK_URL_ALL`). |

**Location filter** (`US_CANADA_ONLY`): a role is kept if its location names a US
state/Canadian province, a US/Canada city, `US-`/`CA-` prefix, or "United
States"/"Canada"; dropped if it clearly names another country/city; kept if
unknown (unless `INCLUDE_UNKNOWN_LOCATIONS=false`). Google is filtered at query
time since its listings carry no parseable location.

**Freshness is dedup-based, not date-based.** A role alerts the first time the
scraper sees it (new id not in state) — that's what "just dropped" actually means.
We deliberately do **not** gate on the board's self-reported posted date: many
boards (Lever especially) report the *requisition-creation* date, not when a role
goes live, so a job published today can carry a months-old date. Gating on that
silently hides real new postings (this exact bug missed a Palantir internship).
First-run seeding prevents the initial backlog from flooding you; after that,
dedup + the 5-min cadence mean you get each role within minutes of it appearing.

**Freshness in the alert**: each notification shows a **🕐 Posted** field. For the
boards that expose an exact timestamp (Greenhouse, Lever, Ashby, and most others)
it's a Discord *live relative time* — so a fresh drop reads "Posted 6 minutes ago"
and keeps counting up. Day-granularity boards (Amazon, Workday) show "today" /
"N days ago". In steady state most alerts will read minutes-old.

Matching logic lives in `jobscraper/filters.py` — tweak the keyword lists there to
broaden/narrow what counts as a SWE/intern/new-grad role.

---

## Adding & fixing companies

**Fastest way — let the `discover` tool find the config:**

```bash
python -m jobscraper.discover "Databricks"                         # guess by name
python -m jobscraper.discover https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers
```

It detects the ATS (Greenhouse / Lever / Ashby / Workday), verifies the endpoint
actually returns jobs, and prints a ready-to-paste `companies.md` row. For a
disabled Workday/custom company: open its careers page, copy the real board URL
from the address bar (or DevTools → Network tab), and pass that URL to `discover`.

If it prints ❌, the company runs a custom/JS-rendered site with no clean public
API — see "Why some stay disabled" below.

You can also do it by hand. Edit the table in **`companies.md`** — add a row, or
flip the **On** column to `no` to pause one. Finding a company's config:

- **Greenhouse** — board lives at `boards.greenhouse.io/<token>`; use that token.
  Verify: `curl https://boards-api.greenhouse.io/v1/boards/<token>/jobs`
- **Lever** — board at `jobs.lever.co/<slug>`.
  Verify: `curl https://api.lever.co/v0/postings/<slug>?mode=json`
- **Ashby** — board at `jobs.ashbyhq.com/<slug>`.
  Verify: `curl https://api.ashbyhq.com/posting-api/job-board/<slug>`
- **Workday** — open the company's Workday careers page; the URL is
  `https://<host>/<tenant>/<site>`. Use those three values.

If a company shows `0 fetched` with an error in the run log, the token/slug/config
is wrong — fix it in `companies.md`.

---

## How do I know alerts are actually fresh (not old jobs newly surfaced)?

Three layers:

1. **Per alert — the 🕐 Posted field.** Every notification shows the real posting
   time. For most boards it's a live "Posted 6 minutes ago" — that *is* the proof
   the posting is fresh, not just newly seen by a cron run.
2. **The guarantee — `MAX_AGE_DAYS=1`.** Even if an old job is "new to us" (e.g. a
   board gets added, or a role re-appears with a new id), it won't alert unless its
   *posting date* is within 24 h. Dedup stops repeats; this stops stale surfacing.
3. **Audit the history — `python -m jobscraper.audit`.** For every job alerted, it
   reports the **catch latency** (time between the board posting it and us alerting):

   ```
   Most recent alerts — 'caught after' = time between posting and our alert:
     caught after   company          title
               2m   Stripe           Software Engineer, New Grad
               1.0h Ramp             New Grad SWE
   Freshness of N audited alerts:
     caught within 1 hour of posting : .../...  (XX%)
     caught within 24 hours          : .../...  (100%)
     ✅ Every alert was for a posting newer than 24h. Working as intended.
   ```

   Small latencies = you're catching genuinely new postings. Any row >24 h gets a
   ⚠️ STALE flag (the only way that happens is a board that exposes no posting date
   — currently just Google — where freshness relies on dedup alone). Posting times
   are recorded from now on, so the audit fills in as new alerts arrive.

## Why some stay disabled

A company is `On=no` when it has **no clean public job API**:

- **Custom / JS-rendered sites** (Jane Street, Bloomberg, Citadel, Two Sigma,
  Tesla, the banks, Apple, Meta, Microsoft, LinkedIn, Indeed): the listings are
  rendered by JavaScript and/or sit behind anti-bot protection. Reading them
  reliably needs a full headless browser (Playwright/Selenium) per site, which is
  brittle and high-maintenance — every site is a one-off that breaks on redesign.
- **Workday/SmartRecruiters with an unknown board**: these *do* have an API; you
  just need the right URL. Run `discover` on the board URL to wire them up.

The scraper deliberately targets **known ATS platforms with stable JSON APIs**
instead of scraping arbitrary HTML — that's why the 130+ enabled companies are
reliable and the disabled ones aren't. Adding a new *platform* adapter (e.g.
SmartRecruiters, iCIMS, Eightfold) is the scalable way to unlock more companies;
chasing individual custom sites is not.

…but the **Simplify source closes much of that gap anyway** (see below).

## Extra source: the Simplify aggregator

On top of the direct APIs, the run also pulls
[SimplifyJobs](https://github.com/SimplifyJobs)' community listing repos
(`Summer2026-Internships`, `New-Grad-Positions`) and alerts on new postings whose
company is in `companies.md`. Why it matters:

- **It covers the disabled custom-site companies.** Simplify currently lists
  hundreds of roles from companies we can't scrape directly — Tesla, Apple,
  ByteDance, Oracle, etc. — so those now produce alerts too.
- Same role/location/recency filters apply, so it only adds *fresh* matches, and
  dedup means a role found both directly and via Simplify won't double-alert.
- These alerts carry a **"via Simplify"** footer. Toggle with `SIMPLIFY_ENABLED`.

### All-companies feed (second channel)

Set `DISCORD_WEBHOOK_URL_ALL` (a second Discord webhook, e.g. in its own
`#internship-radar-all` channel) to also get **every** SWE intern/new-grad role
Simplify lists — no `companies.md`/prestige filter at all. It's the same
role/location filters as everything else, just no company gate.

- A role never fires on both channels: if it's from a company already tracked
  in `companies.md`, it goes out on the main webhook only.
- Turning this on doesn't dump the whole existing backlog into your new channel —
  it does its own quiet first-run seed (one "I'm live" summary) the first time
  `DISCORD_WEBHOOK_URL_ALL` is configured, same as the main feed's first run.
- Leave `DISCORD_WEBHOOK_URL_ALL` unset to skip this feed entirely (default).

## Scheduling reality check

- GitHub's cron minimum is **5 minutes** (`*/5`). In practice scheduled runs are
  often **delayed 5–15 min** during busy periods and a run is occasionally
  **skipped** entirely — GitHub does not guarantee on-time scheduled execution.
  For most internship hunts that's fine; you'll still hear within ~10-20 min.
- Want it tighter/guaranteed? Options: run the same `python -m jobscraper` on a
  cheap always-on box via cron, or on your Mac via `launchd`. The script is
  identical; only the scheduler changes.
