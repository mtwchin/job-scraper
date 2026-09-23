"""Apple server-rendered internship search and requisition identity."""
import json

import pytest

from jobscraper import filters, settings
from jobscraper.adapters import apple
from jobscraper.models import CompanyConfig


def _page(postings, total):
    payload = {"loaderData": {"search": {
        "searchResults": postings, "totalRecords": total,
    }}}
    return '<script>window.__staticRouterHydrationData = JSON.parse(' + json.dumps(json.dumps(payload)) + ')</script>'


def test_fetch_parses_stable_req_id_location_and_posted_time(monkeypatch):
    posting = {
        "reqId": "200664320-3810",
        "transformedPostingTitle": "software-engineering-masters-internships",
        "postingTitle": "Software Engineering Masters Internships",
        "locations": [{"name": "United States"}],
        "postDateInGMT": "2026-09-22T18:00:00Z",
    }
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern", "new_grad"})
    monkeypatch.setattr(apple.http, "get", lambda *a, **kw: type("R", (), {
        "text": _page([posting], 1), "raise_for_status": lambda self: None,
    })())
    jobs = apple.fetch(CompanyConfig("Apple", "apple"))
    assert len(jobs) == 1
    assert jobs[0].job_id == "200664320-3810"
    assert jobs[0].url.endswith("/details/200664320-3810/software-engineering-masters-internships")
    assert jobs[0].location == "United States"
    assert jobs[0].posted_at == "2026-09-22T18:00:00Z"
    assert filters.matches(jobs[0], {"intern"}, False)


def test_invalid_page_fails_instead_of_appearing_empty():
    with pytest.raises(ValueError, match="omitted job data"):
        apple._search_data("<html>blocked</html>")
