"""Apple — jobs.apple.com search API. Needs a CSRF token from the search page."""
from __future__ import annotations

import re

from .. import http
from ..models import CompanyConfig, Job

PAGE = "https://jobs.apple.com/en-us/search"
SEARCH = "https://jobs.apple.com/api/role/search"
_CSRF_RE = re.compile(r'"csrf_token"\s*:\s*"([^"]+)"')


def _csrf_token() -> str | None:
    resp = http.get(PAGE)
    if resp.status_code != 200:
        return None
    # Token shows up in an embedded JSON blob, or as a response header.
    m = _CSRF_RE.search(resp.text)
    if m:
        return m.group(1)
    return resp.headers.get("X-Apple-CSRF-Token")


def fetch(company: CompanyConfig) -> list[Job]:
    token = _csrf_token()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["X-Apple-CSRF-Token"] = token

    jobs: dict[str, Job] = {}
    for query in ("software engineer intern", "software engineering graduate"):
        body = {"query": query, "page": 1, "locale": "en-us", "sort": "newest"}
        resp = http.post(SEARCH, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for j in data.get("searchResults", []):
            pid = str(j.get("positionId") or j.get("id"))
            title = j.get("postingTitle") or j.get("title", "")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            url = f"https://jobs.apple.com/en-us/details/{pid}/{slug}" if pid else ""
            locs = j.get("locations") or []
            location = ", ".join(
                l.get("name", "") for l in locs if isinstance(l, dict)
            ) if isinstance(locs, list) else ""
            jobs[pid] = Job(
                company=company.name,
                job_id=pid,
                title=title,
                url=url,
                location=location,
                posted_at=j.get("postingDate", "") or j.get("postDateInGMT", ""),
            )
    return list(jobs.values())
