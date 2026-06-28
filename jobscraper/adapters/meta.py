"""Meta — metacareers.com GraphQL search.

Meta's GraphQL gateway requires a persisted-query doc_id that changes over time,
so this adapter is best-effort: if the request shape stops working it degrades to
returning nothing (and main.py logs it) rather than crashing the whole run.
"""
from __future__ import annotations

from .. import http
from ..models import CompanyConfig, Job

GRAPHQL = "https://www.metacareers.com/graphql"


def fetch(company: CompanyConfig) -> list[Job]:
    # Public, unauthenticated CareersJobSearchResultsQuery.
    variables = {
        "search_input": {
            "q": "software engineer",
            "divisions": [],
            "offices": [],
            "roles": [],
            "leadership_levels": [],
            "saved_jobs": [],
            "saved_searches": [],
            "sort_by_new": True,
            "page": 1,
            "results_per_page": 100,
        }
    }
    data = {
        "variables": __import__("json").dumps(variables),
        "doc_id": "9114524511922157",  # CareersJobSearchResultsQuery (may rotate)
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
    }
    resp = http.post(GRAPHQL, data=data, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    results = (
        payload.get("data", {})
        .get("job_search_with_featured_jobs", {})
        .get("all_jobs", [])
    ) or payload.get("data", {}).get("job_search", [])

    jobs = []
    for j in results or []:
        jid = str(j.get("id"))
        url = f"https://www.metacareers.com/jobs/{jid}/"
        locs = j.get("locations") or []
        location = ", ".join(locs) if isinstance(locs, list) else str(locs)
        jobs.append(
            Job(
                company=company.name,
                job_id=jid,
                title=j.get("title", ""),
                url=url,
                location=location,
            )
        )
    return jobs
