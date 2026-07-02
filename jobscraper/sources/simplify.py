"""SimplifyJobs GitHub listing repos as an extra source.

Pulls each repo's listings.json and yields software intern / new-grad roles whose
company is in companies.md. We trust Simplify's own `category` classification for
"is this software?" (so titles like "Systems Engineer Intern" are caught), and
match companies on a normalized name plus a small alias map (TikTok→ByteDance …).
Valuable because it also covers the disabled custom-site companies we can't scrape.
"""
from __future__ import annotations

import re

from .. import http, log, settings
from ..companies import load_companies
from ..models import Job

logger = log.get()

_SUFFIXES = ("incorporated", "inc", "llc", "ltd", "corporation", "corp", "labs",
             "technologies", "capital", "trading", "group", "holdings", "ai")

# Simplify categories we treat as software-engineering roles.
SOFTWARE_CATEGORIES = {"Software", "Software Engineering"}

# Simplify's company name (normalized) -> our normalized name, for brand mismatches.
ALIASES = {
    "tiktok": "bytedance",
    "googledeepmind": "deepmind",
    "aws": "amazon",
    "amazonwebservices": "amazon",
    "metaplatforms": "meta",
    "alphabet": "google",
    "rocketlabusa": "rocketlab",
}


def normalize_company(name: str) -> str:
    """Lowercase, drop parentheticals and punctuation, strip a trailing suffix."""
    name = re.sub(r"\(.*?\)", "", name.lower())
    name = re.sub(r"[^a-z0-9]+", "", name)
    for suf in _SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf) + 2:
            name = name[: -len(suf)]
            break
    return name


def our_company_names() -> set[str]:
    return {normalize_company(c.name) for c in load_companies(settings.COMPANIES_FILE)}


def _matches_company(cn: str, ours: set[str]) -> bool:
    n = normalize_company(cn)
    return n in ours or (n in ALIASES and ALIASES[n] in ours)


def _raw_url(repo: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/SimplifyJobs/{repo}/{branch}/.github/scripts/listings.json"


def fetch() -> list[Job]:
    """Active, visible, software intern/new-grad listings from our tracked
    companies. Raises on a hard network failure so main records a source error."""
    ours = our_company_names()
    jobs: dict[str, Job] = {}
    for repo, branch, role in settings.SIMPLIFY_REPOS:
        if settings.ROLE_TYPES and role not in settings.ROLE_TYPES:
            continue
        resp = http.get(_raw_url(repo, branch), retries=1, timeout=25)
        resp.raise_for_status()
        listings = resp.json()
        kept = 0
        for x in listings:
            if not (x.get("active") and x.get("is_visible")):
                continue
            if x.get("category") not in SOFTWARE_CATEGORIES:
                continue
            cn = x.get("company_name", "")
            if not _matches_company(cn, ours):
                continue
            cid = str(x.get("id") or x.get("url"))
            locs = x.get("locations") or []
            jobs[cid] = Job(
                company=cn,
                job_id=f"simplify-{cid}",
                title=x.get("title", ""),
                url=x.get("url", ""),
                location=", ".join(locs) if isinstance(locs, list) else str(locs),
                posted_at=str(x.get("date_posted", "")),  # unix seconds
                source="simplify",
            )
            kept += 1
        logger.debug("simplify %s@%s: %d listings, %d software from our companies",
                     repo, branch, len(listings), kept)
    return list(jobs.values())
