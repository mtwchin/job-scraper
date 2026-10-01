"""Public Oracle Candidate Experience job search (currently JPMorgan Chase)."""
from __future__ import annotations

import concurrent.futures as cf

from .. import http
from ..models import CompanyConfig, Job

_PAGE_SIZE = 200
# JPMC lists ~7,400 requisitions (37 pages). Fetched one after another that took
# ~90s, and since a sweep waits on its slowest board, it stalled every full sweep
# by that much. Pages are independent once the first one reports the total.
_PAGE_WORKERS = 8


def _page(company: CompanyConfig, api: str, site: str, offset: int) -> tuple[int, list[dict]]:
    """One page of the board: (TotalJobsCount, requisitions)."""
    finder = (
        f"findReqs;siteNumber={site},limit={_PAGE_SIZE},offset={offset},"
        "sortBy=POSTING_DATES_DESC"
    )
    response = http.get(
        api,
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        },
        retries=1,
        timeout=20,
    )
    response.raise_for_status()
    items = response.json().get("items")
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError(f"Oracle search returned unexpected response for {company.name}")
    page = items[0]
    requisitions = page.get("requisitionList")
    if not isinstance(requisitions, list):
        raise ValueError(f"Oracle search omitted requisitions for {company.name}")
    total = int(page["TotalJobsCount"])
    if offset < total and not requisitions:
        raise ValueError(f"Oracle search returned an empty page for {company.name}")
    return total, requisitions


def fetch(company: CompanyConfig) -> list[Job]:
    host = company.params.get("host")
    site = company.params.get("site")
    if not (host and site):
        raise ValueError("oracle adapter requires config 'host=;site='")

    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    # Fetch the entire board. Oracle's date is not proof of when a requisition
    # became visible, so stopping at an age cutoff would miss jobs that just
    # went live under an older requisition date.
    total, first = _page(company, api, site, 0)
    pages = [first]
    offsets = range(len(first), total, _PAGE_SIZE) if first else range(0)
    if offsets:
        with cf.ThreadPoolExecutor(max_workers=_PAGE_WORKERS) as ex:
            pages.extend(reqs for _, reqs in ex.map(
                lambda off: _page(company, api, site, off), offsets))

    jobs: dict[str, Job] = {}
    for requisitions in pages:
        for posting in requisitions:
            job_id = str(posting["Id"])
            locations = [posting.get("PrimaryLocation") or ""]
            locations.extend(
                loc.get("Name", "") for loc in posting.get("secondaryLocations") or []
            )
            jobs[job_id] = Job(
                company=company.name,
                job_id=job_id,
                title=posting.get("Title") or "",
                url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}/",
                location="; ".join(loc for loc in locations if loc),
                posted_at=posting.get("PostedDate") or "",
            )
    return list(jobs.values())
