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
