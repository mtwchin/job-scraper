"""Apple's public, server-rendered student internship search.

The search HTML embeds its loader data, including exact posting timestamps and
stable requisition IDs. Reading that data avoids the retired CSRF search API.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from .. import http, settings
from ..models import CompanyConfig, Job

SEARCH = "https://jobs.apple.com/en-us/search"
_HYDRATION = "window.__staticRouterHydrationData = JSON.parse("
_PAGE_SIZE = 20
_MAX_PAGES = 20


def _search_data(html: str) -> dict:
    start = html.find(_HYDRATION)
    if start < 0:
        raise ValueError("Apple search page omitted job data")
    start += len(_HYDRATION)
    try:
        encoded, _ = json.JSONDecoder().raw_decode(html[start:])
        data = json.loads(encoded)["loaderData"]["search"]
        if not isinstance(data["searchResults"], list):
            raise TypeError("searchResults is not a list")
        return data
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Apple search page has invalid job data") from exc


def fetch(company: CompanyConfig) -> list[Job]:
    if "intern" not in settings.ROLE_TYPES:
        return []
    jobs: dict[str, Job] = {}
    for page in range(1, _MAX_PAGES + 1):
        response = http.get(
            SEARCH,
            params={"team": "stages-STDNT-INTRN", "page": page},
            retries=1,
        )
        response.raise_for_status()
        data = _search_data(response.text)
        postings = data["searchResults"]
        if page == 1 and not postings and data.get("totalRecords", 0):
            raise ValueError("Apple search reported jobs but returned no listings")
        for posting in postings:
            req_id = str(posting.get("reqId") or "")
            slug = posting.get("transformedPostingTitle") or ""
            if not req_id or not slug:
                continue
            locations = posting.get("locations") or []
            jobs[req_id] = Job(
                company=company.name,
                job_id=req_id,
                title=posting.get("postingTitle") or "",
                url=f"https://jobs.apple.com/en-us/details/{quote(req_id)}/{quote(slug)}",
                location=", ".join(loc.get("name", "") for loc in locations if isinstance(loc, dict)),
                posted_at=posting.get("postDateInGMT") or posting.get("postingDate") or "",
            )
        if not postings or page * _PAGE_SIZE >= data.get("totalRecords", 0):
            break
    else:
        raise ValueError("Apple internship search exceeded pagination limit")
    return list(jobs.values())
