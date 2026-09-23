"""Runtime configuration, mostly driven by environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Discord ---------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
# Optional second channel: every SWE intern/new-grad role Simplify lists, with no
# companies.md/prestige filter at all. Leave unset to skip this feed entirely.
DISCORD_WEBHOOK_URL_ALL = os.environ.get("DISCORD_WEBHOOK_URL_ALL", "").strip()

# --- Files -----------------------------------------------------------------
COMPANIES_FILE = Path(os.environ.get("COMPANIES_FILE", ROOT / "companies.md"))
STATE_FILE = Path(os.environ.get("STATE_FILE", ROOT / "seen_jobs.json"))

# --- What counts as a match ------------------------------------------------
# Comma-separated subset of {"intern", "new_grad"}.
ROLE_TYPES = {
    r.strip()
    for r in os.environ.get("ROLE_TYPES", "intern,new_grad").split(",")
    if r.strip()
}

# When True, intern roles whose title clearly says "Summer" (and no other
# season) are dropped, so you only get off-season (fall/winter/spring) interns.
# New-grad roles are unaffected.
OFF_SEASON_ONLY = os.environ.get("OFF_SEASON_ONLY", "false").lower() in {"1", "true", "yes"}

# --- Location: US + Canada only --------------------------------------------
# Keep only roles located in the United States or Canada.
US_CANADA_ONLY = os.environ.get("US_CANADA_ONLY", "true").lower() in {"1", "true", "yes"}
# Some sources give no/ambiguous location (e.g. "4 Locations", or Google). When
# True, those are kept (better to over-notify than miss a US/CA role); when
# False they're dropped.
INCLUDE_UNKNOWN_LOCATIONS = os.environ.get(
    "INCLUDE_UNKNOWN_LOCATIONS", "true"
).lower() in {"1", "true", "yes"}

# --- Freshness -------------------------------------------------------------
# "Newly dropped" is determined by dedup (first time the scraper sees a job) plus
# quiet first-run seeding — NOT by the board's self-reported posted date, which is
# unreliable (some boards report req-creation date, so a freshly-listed role can
# carry a months-old date and would be wrongly hidden).
#
# This value only controls *display*: the "🕐 Posted" field is shown when the
# board's date is within this many days, and suppressed when it's older (so a
# stale board date doesn't show a misleading "Posted 10 months ago" on a job that
# just went live).
STALE_POSTED_DAYS = int(os.environ.get("STALE_POSTED_DAYS", "21"))

# --- Dedup -----------------------------------------------------------------
# Besides the per-source id, collapse postings that share a canonical apply URL
# (always on — two links to the same page are the same job) and, when this is
# true, postings that share company + title + location. The fingerprint catches
# a board reissuing one opening under a fresh requisition id; location is part
# of the key, so the same title genuinely posted in several offices is still
# treated as several openings. Turn it off to accept a few repeats rather than
# risk ever suppressing a distinct role.
FINGERPRINT_DEDUP = os.environ.get("FINGERPRINT_DEDUP", "true").lower() in {"1", "true", "yes"}

# Drop store records for postings that no board has listed in this many days.
# Keyed on last-seen, so a still-open role is never pruned however old it is;
# only genuinely delisted roles age out. Keeps seen_jobs.json from growing
# without bound. 0 disables pruning.
PRUNE_DELISTED_DAYS = int(os.environ.get("PRUNE_DELISTED_DAYS", "0"))

# --- Watch mode ------------------------------------------------------------
# `jobscraper watch` polls continuously inside one process instead of relying on
# the scheduler to re-invoke us. GitHub's cron is throttled hard in practice
# (observed: one run every 2-6 hours against a */5 schedule), so a long-lived
# loop is the only way to get detection latency down to minutes.
#
# Seconds between polls of the cheap aggregator feeds. These are single
# conditional GETs that return 304 when nothing changed, so a short interval
# costs almost nothing.
WATCH_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "60"))
# Seconds between full sweeps of every company's own ATS. Much heavier (hundreds
# of requests), so it runs on its own slower cadence.
WATCH_COMPANY_INTERVAL = int(os.environ.get("WATCH_COMPANY_INTERVAL", "300"))
# Select major-company boards for an extra sweep between full scans. Heavy
# boards such as JPMC remain in the five-minute full sweep.
WATCH_PRIORITY_INTERVAL = int(os.environ.get("WATCH_PRIORITY_INTERVAL", "60"))
PRIORITY_COMPANIES = {
    name.strip().casefold()
    for name in os.environ.get(
        "PRIORITY_COMPANIES",
        "Amazon,Google,Microsoft,Apple,Netflix,Nvidia,Salesforce,Adobe,Intel,"
        "OpenAI,Anthropic,SpaceX,Stripe,Palantir,Databricks,Cloudflare,"
        "Coinbase,Roblox,PayPal",
    ).split(",") if name.strip()
}
# How long the loop runs before exiting cleanly, in seconds. Sized to sit under
# the 6-hour ceiling GitHub puts on a single job, leaving room for the final
# state push.
WATCH_DURATION = int(os.environ.get("WATCH_DURATION", str(5 * 3600 + 30 * 60)))
# Flush state to disk at most this often (seconds) while looping. Any cycle that
# actually sends notifications flushes immediately regardless.
WATCH_FLUSH_INTERVAL = int(os.environ.get("WATCH_FLUSH_INTERVAL", "300"))

# --- Behavior --------------------------------------------------------------
# Print what would be sent, don't actually call Discord and don't save state.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() in {"1", "true", "yes"}

# On the very first run (no state file yet) seed everything as "seen" and send a
# single summary instead of spamming one message per existing posting.
SEED_QUIETLY = os.environ.get("SEED_QUIETLY", "true").lower() in {"1", "true", "yes"}

# --- HTTP ------------------------------------------------------------------
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "25"))
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)

# Discord allows up to 10 embeds per webhook message.
MAX_EMBEDS_PER_MESSAGE = 10
# Safety valve: never send more than this many new jobs in one run.
MAX_NOTIFICATIONS_PER_RUN = int(os.environ.get("MAX_NOTIFICATIONS_PER_RUN", "60"))

# --- Scale & health --------------------------------------------------------
# How many companies to fetch in parallel. Different companies are on different
# hosts, so this doesn't hammer any single API.
CONCURRENCY = int(os.environ.get("CONCURRENCY", "12"))
# If this fraction of companies error in a single run, post a Discord heads-up —
# a systemic break (a platform outage, a shipped bug) rather than one stale board.
HEALTH_ALERT_THRESHOLD = float(os.environ.get("HEALTH_ALERT_THRESHOLD", "0.25"))

# --- Community aggregator feeds --------------------------------------------
# Several community repos publish a machine-readable listings.json of open
# intern / new-grad roles. They're valuable for two reasons: they cover the
# custom-site companies we can't scrape directly (Apple, Meta, Tesla, ...), and
# they're a single small conditional GET, so we can poll them every minute for
# effectively nothing when unchanged.
SIMPLIFY_ENABLED = os.environ.get("SIMPLIFY_ENABLED", "true").lower() in {"1", "true", "yes"}

# (owner, repo, branch, role_type, pre_categorized).
#
# pre_categorized=True means the feed labels each listing with a `category`, so
# we can trust its own "this is a software role" call and skip title matching
# (which catches e.g. "Systems Engineer Intern"). Feeds without that field get
# the normal title-based role filter instead.
AGGREGATOR_FEEDS = [
    ("SimplifyJobs", "Summer2026-Internships", "dev", "intern", True),
    ("SimplifyJobs", "New-Grad-Positions", "dev", "new_grad", True),
    # cvrve's feeds track the following cycle and carry roles Simplify hasn't
    # picked up yet. No `category` field, so these are title-filtered.
    ("vanshb03", "Summer2027-Internships", "dev", "intern", False),
    ("vanshb03", "New-Grad-2027", "dev", "new_grad", False),
]

# Sources whose listings are already curated to software roles upstream, so the
# title-based role filter is skipped for them.
PRE_CATEGORIZED_SOURCES = {"simplify"}

# Also post every company the aggregators list (no companies.md filter) to a
# second channel via DISCORD_WEBHOOK_URL_ALL — for "any SWE role, not just
# prestige-list companies". A job already matched into the curated feed is never
# repeated here. Fetching/seeding only starts once DISCORD_WEBHOOK_URL_ALL is
# set (or DRY_RUN), so turning this on doesn't quietly burn through the backlog
# before the webhook is wired up.
SIMPLIFY_ALL_ENABLED = os.environ.get("SIMPLIFY_ALL_ENABLED", "true").lower() in {"1", "true", "yes"}
