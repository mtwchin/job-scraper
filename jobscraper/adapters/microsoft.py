"""Microsoft — public careers search API (gcsservices.careers.microsoft.com)."""
from __future__ import annotations

from .. import http
from ..models import CompanyConfig, Job

SEARCH = "https://gcsservices.careers.microsoft.com/search/api/v1/search"


def fetch(company: CompanyConfig) -> list[Job]:
    jobs: dict[str, Job] = {}
    for query in (
        "software engineer intern",
        "software engineer new grad",
        "software engineer graduate",
    ):
        params = {
            "q": query,
            "l": "en_us",
            "pg": 1,
            "pgSz": 40,
            "o": "Recent",
            "flt": "true",
        }
        resp = http.get(SEARCH, params=params, headers={"Accept": "application/json"})
        resp.raise_for_status()
        result = resp.json().get("operationResult", {}).get("result", {})
        for j in result.get("jobs", []):
            jid = str(j.get("jobId"))
            url = f"https://jobs.careers.microsoft.com/global/en/job/{jid}"
            props = j.get("properties", {}) or {}
            locs = props.get("locations") or props.get("primaryLocation") or []
            location = ", ".join(locs) if isinstance(locs, list) else str(locs)
            jobs[jid] = Job(
                company=company.name,
                job_id=jid,
                title=j.get("title", ""),
                url=url,
                location=location,
                posted_at=props.get("posted", "") or j.get("postingDate", ""),
            )
    return list(jobs.values())
