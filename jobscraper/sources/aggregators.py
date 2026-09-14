"""Community `listings.json` feeds (SimplifyJobs, cvrve/vanshb03) as sources.

Each feed is one JSON document of currently-open intern / new-grad roles. They
matter for two reasons:

* Coverage — they list the custom-site companies we cannot scrape directly.
* Latency — a feed is a single GET that supports conditional requests, so a
  poll that finds nothing new costs one 304 and no body at all. That is what
  makes a once-a-minute cadence affordable.

`fetch_pair()` returns two views from one fetch: `curated` (company is in
companies.md) and `all` (every company). Feeds that carry their own `category`
field are trusted for the "is this software?" call; the rest fall back to the
normal title-based role filter downstream.
"""
from __future__ import annotations

import threading

from .. import filters, http, log, settings
from ..companies import load_companies
from ..dedup import normalize_company
from ..models import Job

logger = log.get()

# Simplify categories we treat as software-engineering roles.
SOFTWARE_CATEGORIES = {"Software", "Software Engineering"}

# Feed's company name (normalized) -> our normalized name, for brand mismatches.
ALIASES = {
    "tiktok": "bytedance",
    "google deepmind": "deepmind",
    "aws": "amazon",
    "amazon web services": "amazon",
    "meta platforms": "meta",
    "alphabet": "google",
    "rocket lab usa": "rocketlab",
    "x formerly twitter": "x",
}

# Conditional-request cache: feed url -> (etag, last_modified, parsed listings).
# Guarded by a lock because a watch loop may poll feeds from a worker thread.
_cache: dict[str, tuple[str, str, list[dict]]] = {}
_cache_lock = threading.Lock()


def our_company_names() -> set[str]:
    return {normalize_company(c.name) for c in load_companies(settings.COMPANIES_FILE)}


def _matches_company(name: str, ours: set[str]) -> bool:
    n = normalize_company(name)
    if n in ours:
        return True
    alias = ALIASES.get(n)
    return bool(alias and alias in ours)


def _raw_url(owner: str, repo: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/.github/scripts/listings.json"


def _to_job(x: dict, source: str) -> Job:
    cid = str(x.get("id") or x.get("url"))
    locs = x.get("locations") or []
    return Job(
        company=x.get("company_name", ""),
        job_id=f"{source}-{cid}",
        title=x.get("title", ""),
        url=x.get("url", ""),
        location=", ".join(locs) if isinstance(locs, list) else str(locs),
        posted_at=str(x.get("date_posted", "")),  # unix seconds
        source=source,
    )


def _fetch_listings(url: str) -> tuple[list[dict], bool]:
    """GET a feed, using If-None-Match / If-Modified-Since.

    Returns (listings, changed). On 304 we return the cached body and
    changed=False, which lets a caller skip re-filtering entirely. Raises on a
    hard network failure so the caller can record a source error.
    """
    with _cache_lock:
        cached = _cache.get(url)
    headers = {"Accept-Encoding": "gzip"}
    if cached:
        etag, last_mod, _ = cached
        if etag:
            headers["If-None-Match"] = etag
        if last_mod:
            headers["If-Modified-Since"] = last_mod

    resp = http.get(url, headers=headers, retries=1, timeout=30)
    if resp.status_code == 304:
        if cached:
            return cached[2], False
        # We only send a validator when we hold a cached body, so this means the
        # cache went away underneath us (or something upstream answered 304
        # unprompted). raise_for_status() won't catch it — 304 isn't an error
        # status — and falling through would hand the caller an empty feed,
        # which reads as "every job was delisted". Say so instead.
        raise RuntimeError(f"304 Not Modified for {url} but nothing is cached")
    resp.raise_for_status()
    listings = resp.json()
    if not isinstance(listings, list):
        raise ValueError(f"expected a JSON array of listings, got {type(listings).__name__}")
    with _cache_lock:
        _cache[url] = (
            resp.headers.get("ETag", ""),
            resp.headers.get("Last-Modified", ""),
            listings,
        )
    return listings, True


def _is_software(listing: dict, pre_categorized: bool) -> bool:
    """Whether a listing is a software role.

    Feeds carrying `category` are trusted (they catch titles like "Systems
    Engineer Intern" that a title match would miss). Feeds without it get the
    title check here so the uncategorized feeds don't flood us with non-SWE
    roles. A `category`-bearing feed that omits it on a given row falls back to
    the title check rather than dropping the row.
    """
    category = listing.get("category")
    if pre_categorized and category is not None:
        return category in SOFTWARE_CATEGORIES
    return filters.is_swe(listing.get("title", ""))


def fetch_pair() -> tuple[list[Job], list[Job], bool]:
    """Fetch every configured feed and split into (curated, all, changed).

    `changed` is False only when every feed answered 304 — nothing anywhere has
    moved since the last poll, so the caller can skip the rest of the cycle.
    A feed that errors is logged and skipped rather than failing the sweep; if
    *every* feed fails we raise, since that is a real outage worth surfacing.
    """
    ours = our_company_names()
    curated: dict[str, Job] = {}
    all_jobs: dict[str, Job] = {}
    any_changed = False
    errors: list[str] = []
    attempted = 0

    for owner, repo, branch, role, pre_categorized in settings.AGGREGATOR_FEEDS:
        if settings.ROLE_TYPES and role not in settings.ROLE_TYPES:
            continue
        attempted += 1
        source = "simplify" if owner == "SimplifyJobs" else owner.lower()
        url = _raw_url(owner, repo, branch)
        try:
            listings, changed = _fetch_listings(url)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not sink the rest
            errors.append(f"{owner}/{repo}: {type(exc).__name__}: {exc}")
            logger.debug("aggregator %s/%s failed: %s", owner, repo, exc)
            continue
        any_changed = any_changed or changed

        kept = 0
        for x in listings:
            if not (x.get("active") and x.get("is_visible")):
                continue
            if not _is_software(x, pre_categorized):
                continue
            kept += 1
            job = _to_job(x, source)
            all_jobs.setdefault(job.job_id, job)
            if _matches_company(job.company, ours):
                curated.setdefault(job.job_id, job)
        logger.debug("aggregator %s/%s@%s: %d listings, %d software (changed=%s)",
                     owner, repo, branch, len(listings), kept, changed)

    if attempted and len(errors) == attempted:
        raise RuntimeError("; ".join(errors))
    for err in errors:
        logger.warning("aggregator feed failed: %s", err)
    return list(curated.values()), list(all_jobs.values()), any_changed


def fetch() -> list[Job]:
    """Listings from our tracked companies only."""
    curated, _all, _changed = fetch_pair()
    return curated
