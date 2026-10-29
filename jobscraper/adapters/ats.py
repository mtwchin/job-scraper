"""Generic adapters for shared ATS platforms: Greenhouse, Lever, Ashby, Workday, Eightfold."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import replace

from .. import filters, http, settings
from ..models import CompanyConfig, Job

_ROLE_QUERIES = (
    "software engineer intern",
    "software engineer new grad",
    "software engineer graduate",
    "software developer intern",
    "associate software engineer",
)


# --------------------------------------------------------------------------- #
# Greenhouse:  https://boards-api.greenhouse.io/v1/boards/<token>/jobs
# --------------------------------------------------------------------------- #
def fetch_greenhouse(company: CompanyConfig) -> list[Job]:
    token = company.params.get("token")
    if not token:
        raise ValueError("greenhouse adapter requires config 'token='")
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    resp = http.get(url, params={"content": "false"})
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(
            Job(
                company=company.name,
                job_id=str(j.get("id")),
                title=j.get("title", ""),
                url=j.get("absolute_url", ""),
                location=loc,
                posted_at=j.get("updated_at", "") or j.get("first_published", ""),
            )
        )
    return jobs


# --------------------------------------------------------------------------- #
# Lever:  https://api.lever.co/v0/postings/<slug>?mode=json
# --------------------------------------------------------------------------- #
def fetch_lever(company: CompanyConfig) -> list[Job]:
    slug = company.params.get("slug")
    if not slug:
        raise ValueError("lever adapter requires config 'slug='")
    url = f"https://api.lever.co/v0/postings/{slug}"
    resp = http.get(url, params={"mode": "json"})
    resp.raise_for_status()
    jobs = []
    for j in resp.json():
        cats = j.get("categories") or {}
        jobs.append(
            Job(
                company=company.name,
                job_id=str(j.get("id")),
                title=j.get("text", ""),
                url=j.get("hostedUrl", ""),
                location=cats.get("location", "") or "",
                posted_at=str(j.get("createdAt", "")),
            )
        )
    return jobs


# --------------------------------------------------------------------------- #
# Workday:  POST https://<host>/wday/cxs/<tenant>/<site>/jobs
# --------------------------------------------------------------------------- #
# Workday boards hold thousands of roles, so instead of grabbing the first page
# of everything we run several targeted searches (each returns a small, fully
# paginatable set) and merge. This reliably surfaces the intern/new-grad roles we
# care about instead of truncating at an arbitrary 40.
_WORKDAY_QUERIES = (
    "",  # newest-first listing; see _WORKDAY_NEWEST_PAGES
    "software engineer intern",
    "software engineer new grad",
    "software engineer graduate",
    "software developer intern",
    "early career software",
    "associate software engineer",
)
_WORKDAY_PAGE = 20
_WORKDAY_MAX_PER_QUERY = 200
# Results are relevance-ranked, so past the point where whole pages hold no
# intern/new-grad title, further pages are noise. Stop a query after this many
# such pages in a row rather than walking all ten.
_WORKDAY_IRRELEVANT_PAGES = 2
_GENERIC_LOCATION = re.compile(r"^\d+\s+locations?$", re.I)
# An empty search lists the board newest-first by posting day, so walking its
# "Posted Today" pages sees every new posting however it is titled or ranked.
# The keyword queries alone missed roles that relevance buried under dozens of
# overseas interns (NVIDIA), leaving them to the aggregator feeds hours later.
# Within a day the order isn't by time, hence every Today page, not just one.
_WORKDAY_NEWEST_PAGES = 8
_WORKDAY_TODAY = re.compile(r"\btoday\b|just posted", re.I)

# Every tenant sits on Workday's shared infrastructure, and it rate-limits by
# client IP across all of them: when it decided our runner was too busy, all ten
# Workday companies failed at once (HTTP 500s, then empty 200 bodies) for hours.
# Capping our concurrent Workday requests keeps the sweep's burst modest.
_WORKDAY_SLOTS = threading.BoundedSemaphore(3)
# Quick sweeps get slots of their own. Sharing, they queued behind a
# full sweep's ~250 Workday requests and a 4s look at NVIDIA took 50s. Their
# whole sweep is a dozen-odd requests, so this adds little to the burst.
_WORKDAY_QUICK_SLOTS = threading.BoundedSemaphore(2)
# A posting's offices don't change, so resolve each "2 Locations" posting once
# per process instead of re-fetching its detail page every sweep.
_workday_locations: dict[str, str] = {}
_WORKDAY_LOCATION_CACHE_MAX = 5000


def _workday_call(fn, url: str, quick: bool = False, **kwargs):
    """One Workday request: bounded concurrency, a clear error for a throttled
    (non-JSON) answer, and a single patient retry for one."""
    for attempt in range(2):
        with _WORKDAY_QUICK_SLOTS if quick else _WORKDAY_SLOTS:
            resp = fn(url, retries=1, timeout=20, **kwargs)
        resp.raise_for_status()
        try:
            return http.json_body(resp)
        except http.NotJSON:
            if attempt:
                raise
        time.sleep(3)


def _workday_relevant(title: str) -> bool:
    probe = Job(company="", job_id="", title=title, url="", location="")
    return filters.matches(probe, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY)


def fetch_workday(company: CompanyConfig) -> list[Job]:
    host = company.params.get("host")
    tenant = company.params.get("tenant")
    site = company.params.get("site")
    if not (host and tenant and site):
        raise ValueError("workday adapter requires config 'host=;tenant=;site='")

    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    jobs: dict[str, Job] = {}
    detail_paths: dict[str, str] = {}

    # A quick sweep runs only the newest-first pass: it is what
    # catches a fresh posting, at a fraction of the keyword queries' requests.
    for query in ("",) if company.quick else _WORKDAY_QUERIES:
        newest = not query
        limit = _WORKDAY_NEWEST_PAGES * _WORKDAY_PAGE if newest else _WORKDAY_MAX_PER_QUERY
        offset = 0
        total = None
        irrelevant_pages = 0
        while offset < limit:
            body = {
                "appliedFacets": {},
                "limit": _WORKDAY_PAGE,
                "offset": offset,
                "searchText": query,
            }
            # Bound time so one slow Workday host can't stall the whole run
            # (a failure here is caught per-company by main.py).
            data = _workday_call(http.post, api, quick=company.quick, json=body, headers=headers)
            postings = data.get("jobPostings", [])
            if not postings:
                break
            # Workday reports `total` on the first page only; later pages say 0.
            # Reading it per page stopped every query after its second page.
            if total is None:
                total = data.get("total", 0)
            for p in postings:
                ext = p.get("externalPath", "")
                # externalPath is "/job/<loc>/<title>_<req>" — the public job URL
                # needs the site segment inserted, else it 404s.
                url = f"https://{host}/{site}{ext}" if ext else ""
                # externalPath is unique + stable; prefer it as the id.
                jid = ext.rsplit("/", 1)[-1] if ext else str(
                    (p.get("bulletFields") or [p.get("title")])[0]
                )
                jobs[jid] = Job(
                    company=company.name,
                    job_id=jid,
                    title=p.get("title", ""),
                    url=url,
                    location=p.get("locationsText", ""),
                    posted_at=p.get("postedOn", ""),
                )
                detail_paths[jid] = ext
            offset += _WORKDAY_PAGE
            if offset >= total:
                break
            if newest:
                if not all(_WORKDAY_TODAY.search(p.get("postedOn", "")) for p in postings):
                    break
                continue
            if any(_workday_relevant(p.get("title", "")) for p in postings):
                irrelevant_pages = 0
            else:
                irrelevant_pages += 1
                if irrelevant_pages >= _WORKDAY_IRRELEVANT_PAGES:
                    break
    # Search results sometimes say only "2 Locations". A posting URL may name
    # one foreign office while another office is in the US, so resolve every
    # relevant ambiguous role from Workday's public detail endpoint.
    if settings.US_CANADA_ONLY:
        for jid, job in list(jobs.items()):
            if not _GENERIC_LOCATION.fullmatch(job.location.strip()):
                continue
            if not filters.matches(job, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY):
                continue
            ext = detail_paths.get(jid)
            if not ext:
                continue
            detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{ext}"
            location = _workday_locations.get(detail_url)
            if location is None:
                info = _workday_call(http.get, detail_url, quick=company.quick).get("jobPostingInfo") or {}
                locations = [info.get("location") or "", *(info.get("additionalLocations") or [])]
                location = ", ".join(loc for loc in locations if loc)
                if not location:
                    raise ValueError(f"Workday detail omitted locations for {jid}")
                if len(_workday_locations) >= _WORKDAY_LOCATION_CACHE_MAX:
                    _workday_locations.clear()
                _workday_locations[detail_url] = location
            jobs[jid] = replace(job, location=location)
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# Eightfold:  GET https://<host>/api/apply/v2/jobs?domain=<domain>&query=...
# --------------------------------------------------------------------------- #
def fetch_eightfold(company: CompanyConfig) -> list[Job]:
    host = company.params.get("host")
    domain = company.params.get("domain")
    if not (host and domain):
        raise ValueError("eightfold adapter requires config 'host=;domain='")
    api = f"https://{host}/api/apply/v2/jobs"
    jobs: dict[str, Job] = {}
    for query in _ROLE_QUERIES:
        start = 0
        while start < 200:
            resp = http.get(
                api,
                params={"domain": domain, "query": query, "start": start, "num": 50},
                retries=1, timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            positions = data.get("positions", [])
            if not positions:
                break
            for p in positions:
                pid = str(p.get("id"))
                locs = p.get("locations") or ([p["location"]] if p.get("location") else [])
                jobs[pid] = Job(
                    company=company.name,
                    job_id=pid,
                    title=p.get("name", ""),
                    url=p.get("canonicalPositionUrl", ""),
                    location=", ".join(locs),
                    posted_at=str(p.get("t_create", "")),  # unix seconds
                )
            start += 50
            if start >= data.get("count", 0):
                break
    return list(jobs.values())
