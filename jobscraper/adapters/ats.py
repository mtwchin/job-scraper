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
def fetch_workday(company: CompanyConfig) -> list[Job]:
    host = company.params.get("host")
    tenant = company.params.get("tenant")
    site = company.params.get("site")
    if not (host and tenant and site):
        raise ValueError("workday adapter requires config 'host=;tenant=;site='")

    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    jobs: list[Job] = []
    offset = 0
    # Pull a couple of pages of most-recent postings.
    for _ in range(2):
        body = {
            "appliedFacets": {},
            "limit": 20,
            "offset": offset,
            "searchText": "software engineer",
        }
        resp = http.post(api, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            ext = p.get("externalPath", "")
            url = f"https://{host}{ext}" if ext else ""
            jobs.append(
                Job(
                    company=company.name,
                    job_id=str(p.get("bulletFields", [p.get("title")])[0] or ext),
                    title=p.get("title", ""),
                    url=url,
                    location=p.get("locationsText", ""),
                    posted_at=p.get("postedOn", ""),
                )
            )
        offset += 20
        if offset >= data.get("total", 0):
            break
    return jobs
