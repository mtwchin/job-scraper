"""Runtime configuration, mostly driven by environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Discord ---------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

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
OFF_SEASON_ONLY = os.environ.get("OFF_SEASON_ONLY", "true").lower() in {"1", "true", "yes"}

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

# --- Simplify aggregator source --------------------------------------------
# Also pull from SimplifyJobs' community GitHub listing repos and alert on new
# postings whose company is in companies.md. This adds coverage — including for
# the disabled custom-site companies (Apple, Meta, Tesla, …) that we can't scrape
# directly but Simplify often lists.
SIMPLIFY_ENABLED = os.environ.get("SIMPLIFY_ENABLED", "true").lower() in {"1", "true", "yes"}
# (repo, branch) pairs on github.com/SimplifyJobs.
SIMPLIFY_REPOS = [
    ("Summer2026-Internships", "dev"),
    ("New-Grad-Positions", "dev"),
]
