"""SimplifyJobs GitHub listing repos as an extra source.

Pulls each repo's listings.json and yields jobs whose company is in companies.md
(matched on a normalized name). The same role/location/recency filters then apply
in main, so this is purely an additional, redundant feed — valuable because it
also covers the disabled custom-site companies we can't scrape directly.
"""
from __future__ import annotations

import re

from .. import http, log, settings
from ..companies import load_companies
from ..models import Job

logger = log.get()

_SUFFIXES = ("incorporated", "inc", "llc", "ltd", "corporation", "corp", "labs",
             "technologies", "capital", "trading", "group", "holdings", "ai")


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


def _raw_url(repo: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/SimplifyJobs/{repo}/{branch}/.github/scripts/listings.json"


def fetch() -> list[Job]:
    """All currently-active listings from our tracked companies. Raises on a hard
    network failure so main can record it as a source error."""
    ours = our_company_names()
    jobs: dict[str, Job] = {}
    for repo, branch in settings.SIMPLIFY_REPOS:
        resp = http.get(_raw_url(repo, branch), retries=1, timeout=25)
        resp.raise_for_status()
        listings = resp.json()
        kept = 0
        for x in listings:
            if not x.get("active"):
                continue
            cn = x.get("company_name", "")
            if normalize_company(cn) not in ours:
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
        logger.debug("simplify %s@%s: %d listings, %d from our companies", repo, branch, len(listings), kept)
    return list(jobs.values())
