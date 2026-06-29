"""Amazon — public amazon.jobs search.json endpoint."""
from __future__ import annotations

from .. import http
from ..models import CompanyConfig, Job

SEARCH = "https://www.amazon.jobs/en/search.json"


def fetch(company: CompanyConfig) -> list[Job]:
    jobs: dict[str, Job] = {}
    # Query a few keyword slices and merge; category narrows to software roles.
    # Amazon titles use "SDE" / "Software Development Engineer", so cover both.
    for query in (
        "software development engineer intern",
        "software engineer intern",
        "software development engineer graduate",
        "software engineer new grad",
    ):
        params = {
            "base_query": query,
            "category[]": "software-development",
            "sort": "recent",
            "result_limit": 100,
            "offset": 0,
        }
        resp = http.get(SEARCH, params=params)
        resp.raise_for_status()
        for j in resp.json().get("jobs", []):
            path = j.get("job_path", "")
            url = f"https://www.amazon.jobs{path}" if path else ""
            jid = str(j.get("id_icims") or path)
            jobs[jid] = Job(
                company=company.name,
                job_id=jid,
                title=j.get("title", ""),
                url=url,
                location=j.get("normalized_location", "") or j.get("location", ""),
                posted_at=j.get("posted_date", ""),
            )
    return list(jobs.values())
