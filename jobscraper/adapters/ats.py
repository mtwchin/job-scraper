"""Generic adapters for the big shared ATS platforms: Greenhouse, Lever, Workday."""
from __future__ import annotations

from .. import http
from ..models import CompanyConfig, Job


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
    "software engineer intern",
    "software engineer new grad",
    "software engineer graduate",
    "software developer intern",
    "early career software",
)
_WORKDAY_PAGE = 20
_WORKDAY_MAX_PER_QUERY = 200


def fetch_workday(company: CompanyConfig) -> list[Job]:
    host = company.params.get("host")
    tenant = company.params.get("tenant")
    site = company.params.get("site")
    if not (host and tenant and site):
        raise ValueError("workday adapter requires config 'host=;tenant=;site='")

    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    jobs: dict[str, Job] = {}

    for query in _WORKDAY_QUERIES:
        offset = 0
        while offset < _WORKDAY_MAX_PER_QUERY:
            body = {
                "appliedFacets": {},
                "limit": _WORKDAY_PAGE,
                "offset": offset,
                "searchText": query,
            }
            # Bound time so one slow Workday host can't stall the whole run
            # (a failure here is caught per-company by main.py).
            resp = http.post(api, json=body, headers=headers, retries=1, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break
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
            offset += _WORKDAY_PAGE
            if offset >= data.get("total", 0):
                break
    return list(jobs.values())
