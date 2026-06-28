"""Ashby — public posting API (api.ashbyhq.com/posting-api/job-board/<slug>)."""
from __future__ import annotations

from .. import http
from ..models import CompanyConfig, Job


def fetch(company: CompanyConfig) -> list[Job]:
    slug = company.params.get("slug")
    if not slug:
        raise ValueError("ashby adapter requires config 'slug='")
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = http.get(url)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        jobs.append(
            Job(
                company=company.name,
                job_id=str(j.get("id")),
                title=j.get("title", ""),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                location=j.get("location", "") or "",
                posted_at=j.get("publishedAt", ""),
            )
        )
    return jobs
