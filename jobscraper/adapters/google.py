"""Google — careers results page is server-rendered; parse job links from the HTML.

The JSON API (careers.google.com/api/v3) is dead, but the public results page at
google.com/about/careers/applications/jobs/results/ embeds links of the form
    jobs/results/<numeric-id>-<slug-with-the-title>
so we scrape those. The title is recovered from the slug.
"""
from __future__ import annotations

import re

from .. import http
from ..models import CompanyConfig, Job

RESULTS = "https://www.google.com/about/careers/applications/jobs/results/"
_LINK_RE = re.compile(r"jobs/results/(\d{6,})-([a-z0-9-]+)")


def fetch(company: CompanyConfig) -> list[Job]:
    jobs: dict[str, Job] = {}
    for query in ("software engineer intern", "software engineer early career"):
        for page in (1, 2, 3):
            resp = http.get(RESULTS, params={"q": query, "page": page})
            if resp.status_code != 200:
                break
            found = _LINK_RE.findall(resp.text)
            if not found:
                break
            for jid, slug in found:
                title = slug.replace("-", " ").strip().title()
                url = f"{RESULTS}{jid}-{slug}"
                jobs[jid] = Job(
                    company=company.name,
                    job_id=jid,
                    title=title,
                    url=url,
                )
    return list(jobs.values())
