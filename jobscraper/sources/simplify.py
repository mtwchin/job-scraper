"""SimplifyJobs GitHub listing repos as an extra source.

Pulls each repo's listings.json and yields software intern / new-grad roles. We
trust Simplify's own `category` classification for "is this software?" (so
titles like "Systems Engineer Intern" are caught). `fetch_pair()` returns two
views from a single fetch: `curated` (company must be in companies.md, matched
on a normalized name plus a small alias map — TikTok→ByteDance …) and `all`
(every company, unfiltered — the "any SWE role" feed). Valuable because it also
covers the disabled custom-site companies we can't scrape directly.
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


def _to_job(x: dict) -> Job:
    cid = str(x.get("id") or x.get("url"))
    locs = x.get("locations") or []
    return Job(
        company=x.get("company_name", ""),
        job_id=f"simplify-{cid}",
        title=x.get("title", ""),
        url=x.get("url", ""),
        location=", ".join(locs) if isinstance(locs, list) else str(locs),
        posted_at=str(x.get("date_posted", "")),  # unix seconds
        source="simplify",
    )


def fetch_pair() -> tuple[list[Job], list[Job]]:
    """Fetch each configured Simplify repo once and split into two views:
    (curated, all). `curated` is restricted to companies.md (our existing
    tracked list); `all` is every active/visible software listing regardless of
    company — fetched once and split so both views cost a single GET per repo
    instead of two. Raises on a hard network failure so main records a source
    error."""
    ours = our_company_names()
    curated: dict[str, Job] = {}
    all_jobs: dict[str, Job] = {}
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
            kept += 1
            job = _to_job(x)
            all_jobs[job.job_id] = job
            if _matches_company(job.company, ours):
                curated[job.job_id] = job
        logger.debug("simplify %s@%s: %d listings, %d software",
                     repo, branch, len(listings), kept)
    return list(curated.values()), list(all_jobs.values())


def fetch() -> list[Job]:
    """Active, visible, software intern/new-grad listings from our tracked
    companies only. Raises on a hard network failure so main records a source
    error."""
    curated, _all = fetch_pair()
    return curated
