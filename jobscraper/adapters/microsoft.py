"""Microsoft's current Eightfold careers search (apply.careers.microsoft.com).

The retired gcsservices endpoint no longer works. The public careers page
supplies a CSRF token for its read-only search API. Fetch it once per pass,
then query the small software-engineering intern/entry pools by posting time.
"""
from __future__ import annotations

import re

from .. import http
from ..models import CompanyConfig, Job

BASE = "https://apply.careers.microsoft.com"
SEARCH = f"{BASE}/api/pcsx/search"
_CSRF = re.compile(r'<meta name="_csrf" content="([^"]+)">')
_PAGE = 10  # observed page size of the public search endpoint
_MAX_RESULTS_PER_LEVEL = 100


def fetch(company: CompanyConfig) -> list[Job]:
    page = http.get(f"{BASE}/careers", retries=1)
    page.raise_for_status()
    match = _CSRF.search(page.text)
    if not match:
        raise ValueError("Microsoft careers page did not include a CSRF token")

    headers = {
        "X-CSRF-Token": match.group(1),
        "Referer": f"{BASE}/careers",
    }
    jobs: dict[str, Job] = {}
    for level in ("Intern", "Entry"):
        for start in range(0, _MAX_RESULTS_PER_LEVEL, _PAGE):
            response = http.get(
                SEARCH,
                params={
                    "domain": "microsoft.com",
                    "query": "",
                    "location": "",
                    "start": start,
                    "sort_by": "timestamp",
                    "filter_seniority": level,
                    "filter_profession": "software engineering",
                },
                headers=headers,
                retries=1,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
                raise ValueError("Microsoft careers search returned an invalid payload")
            data = payload["data"]
            positions = data.get("positions")
            if not isinstance(positions, list):
                raise ValueError("Microsoft careers search omitted positions")
            for position in positions:
                pid = str(position.get("id") or "")
                path = position.get("positionUrl") or ""
                if not pid or not path.startswith("/careers/job/"):
                    continue
                jobs[pid] = Job(
                    company=company.name,
                    job_id=pid,
                    title=position.get("name") or "",
                    url=f"{BASE}{path}",
                    location=", ".join(position.get("locations") or []),
                    posted_at=str(position.get("postedTs") or ""),
                )
            if len(positions) < _PAGE or start + len(positions) >= data.get("count", 0):
                break
    return list(jobs.values())
