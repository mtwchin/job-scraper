"""Google — careers results page is server-rendered; parse job links from the HTML.

The JSON API (careers.google.com/api/v3) is dead, but the public results page at
google.com/about/careers/applications/jobs/results/ embeds links of the form
    jobs/results/<numeric-id>-<slug-with-the-title>
so we scrape those. The title is recovered from the slug.

Google's `q` keyword does NOT filter by seniority (querying "software engineer
intern" returns senior roles), so we use the `target_level` facet to pull the
intern and early-career pools directly, then the shared role filter keeps only
titles that read as intern / new-grad SWE.
"""
from __future__ import annotations

import re

from .. import http, settings
from ..models import CompanyConfig, Job

RESULTS = "https://www.google.com/about/careers/applications/jobs/results/"
_LINK_RE = re.compile(r"jobs/results/(\d{6,})-([a-z0-9-]+)")

# Which Google seniority facet to pull for each role type we track.
_LEVEL_FOR_ROLE = {
    "intern": "INTERN_AND_APPRENTICE",
    "new_grad": "EARLY",
}


def fetch(company: CompanyConfig) -> list[Job]:
    jobs: dict[str, Job] = {}
    # Google's results carry no parseable per-job location, so restrict at query
    # time; each location is queried separately (server-side filter).
    locations = ["United States", "Canada"] if settings.US_CANADA_ONLY else [None]
    levels = [_LEVEL_FOR_ROLE[r] for r in settings.ROLE_TYPES if r in _LEVEL_FOR_ROLE] \
        or list(_LEVEL_FOR_ROLE.values())

    for level in levels:
        for location in locations:
            for page in (1, 2, 3):
                params = {
                    "q": "software engineer",
                    "target_level": level,
                    "page": page,
                    "sort_by": "date",
                }
                if location:
                    params["location"] = location
                resp = http.get(RESULTS, params=params)
                if resp.status_code != 200:
                    break
                found = _LINK_RE.findall(resp.text)
                if not found:
                    break
                for jid, slug in found:
                    title = slug.replace("-", " ").strip().title()
                    jobs[jid] = Job(
                        company=company.name,
                        job_id=jid,
                        title=title,
                        url=f"{RESULTS}{jid}-{slug}",
                        location=location or "",
                    )
    return list(jobs.values())
