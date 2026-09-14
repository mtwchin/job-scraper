"""Adapters for ATS platforms beyond the original four.

Each of these is a public, unauthenticated JSON endpoint that a company's own
careers page calls to render itself, so we read exactly what a visitor's browser
would. Adding a platform adapter is worth more than adding a company: it unlocks
every company already on that platform. SmartRecruiters alone covers several
companies sitting disabled in companies.md with "needs adapter" against them.

Field access is deliberately forgiving — these payloads vary between tenants,
and a missing optional field should cost us one imperfect record, not the whole
company's fetch.
"""
from __future__ import annotations

from typing import Any

from .. import http
from ..models import CompanyConfig, Job


def _text(value: Any) -> str:
    """Coerce whatever a board gave us into a string, treating null as empty."""
    return "" if value is None else str(value)


def _join(*parts: Any) -> str:
    """Comma-join the non-empty parts of a location."""
    return ", ".join(p for p in (_text(x).strip() for x in parts) if p)


# --------------------------------------------------------------------------- #
# SmartRecruiters
#   GET https://api.smartrecruiters.com/v1/companies/<id>/postings?limit&offset
# --------------------------------------------------------------------------- #
_SR_PAGE = 100
_SR_MAX = 1000


def fetch_smartrecruiters(company: CompanyConfig) -> list[Job]:
    company_id = company.params.get("id") or company.params.get("company")
    if not company_id:
        raise ValueError("smartrecruiters adapter requires config 'id=<company identifier>'")

    api = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    jobs: dict[str, Job] = {}
    offset = 0
    while offset < _SR_MAX:
        resp = http.get(api, params={"limit": _SR_PAGE, "offset": offset}, retries=1, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("content") or []
        if not postings:
            break
        for p in postings:
            pid = _text(p.get("id") or p.get("uuid"))
            if not pid:
                continue
            loc = p.get("location") or {}
            # A remote posting often carries no city at all; say so rather than
            # emitting an empty location, which the geo filter reads as unknown.
            location = _join(loc.get("city"), loc.get("region"), loc.get("country"))
            if loc.get("remote") and not location:
                location = "Remote"
            jobs[pid] = Job(
                company=company.name,
                job_id=pid,
                title=_text(p.get("name")),
                url=f"https://jobs.smartrecruiters.com/{company_id}/{pid}",
                location=location,
                posted_at=_text(p.get("releasedDate") or p.get("createdOn")),
            )
        offset += _SR_PAGE
        total = data.get("totalFound")
        if isinstance(total, int) and offset >= total:
            break
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# Workable
#   GET https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true
# --------------------------------------------------------------------------- #
def _workable_location(j: dict) -> str:
    """Build a location string from a Workable widget job.

    Workable does not nest this under a `location` key — the place is carried as
    flat `city`/`state`/`country` fields, plus a `locations` array when a role is
    open in more than one office. Reading a nested object here returns nothing,
    and an empty location is worse than a wrong one: the geo filter treats blank
    as "unknown" and keeps it, so every foreign role would survive a US/Canada
    filter. Prefer the array (it is the complete picture), fall back to the flat
    fields, and only then fall back to the remote flag.
    """
    places = []
    for loc in j.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        if (place := _join(loc.get("city"), loc.get("region"), loc.get("country"))):
            places.append(place)
    if places:
        return "; ".join(dict.fromkeys(places))

    if (flat := _join(j.get("city"), j.get("state"), j.get("country"))):
        return flat
    return "Remote" if j.get("telecommuting") else ""


def fetch_workable(company: CompanyConfig) -> list[Job]:
    slug = company.params.get("slug")
    if not slug:
        raise ValueError("workable adapter requires config 'slug=<account slug>'")

    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    resp = http.get(url, params={"details": "true"}, retries=1, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for j in data.get("jobs") or []:
        # shortcode is the stable public identifier; id is internal and not
        # always present on the widget payload.
        code = _text(j.get("shortcode") or j.get("id"))
        if not code:
            continue
        location = _workable_location(j)
        jobs.append(
            Job(
                company=company.name,
                job_id=code,
                title=_text(j.get("title")),
                url=_text(j.get("url") or f"https://apply.workable.com/{slug}/j/{code}/"),
                location=location,
                posted_at=_text(j.get("published_on") or j.get("created_at")),
            )
        )
    return jobs


# --------------------------------------------------------------------------- #
# Recruitee
#   GET https://<company>.recruitee.com/api/offers/
#
# NOT yet confirmed against a live tenant. The endpoint is Recruitee's documented
# public careers API and the parsing below is unit tested, but every candidate
# tenant tried so far returned 404 (those companies have since moved off the
# platform), so no company is enabled on this adapter. Before switching one on,
# run `jobscraper probe recruitee "slug=<slug>"` and check it returns postings.
# --------------------------------------------------------------------------- #
def fetch_recruitee(company: CompanyConfig) -> list[Job]:
    slug = company.params.get("slug")
    if not slug:
        raise ValueError("recruitee adapter requires config 'slug=<company slug>'")

    url = f"https://{slug}.recruitee.com/api/offers/"
    resp = http.get(url, retries=1, timeout=20)
    resp.raise_for_status()

    jobs = []
    for o in resp.json().get("offers") or []:
        oid = _text(o.get("id"))
        if not oid:
            continue
        location = _join(o.get("city"), o.get("state_code") or o.get("state_name"),
                         o.get("country_code") or o.get("country"))
        if o.get("remote") and not location:
            location = "Remote"
        jobs.append(
            Job(
                company=company.name,
                job_id=oid,
                title=_text(o.get("title")),
                url=_text(o.get("careers_url")
                          or f"https://{slug}.recruitee.com/o/{_text(o.get('slug'))}"),
                location=location,
                posted_at=_text(o.get("published_at") or o.get("created_at")),
            )
        )
    return jobs
