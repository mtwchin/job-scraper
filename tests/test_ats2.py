"""Tests for the SmartRecruiters / Workable / Recruitee adapters.

Payloads here mirror the shape each platform's public endpoint returns. They
cover the parts that actually vary between tenants — missing optional fields,
remote postings with no city, pagination — because that variance is what breaks
an adapter in production, not the happy path.
"""
from __future__ import annotations

import pytest

from jobscraper.adapters import ats2
from jobscraper.models import CompanyConfig


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def company(adapter, **params):
    return CompanyConfig(name="Acme", adapter=adapter, params=params)


# --------------------------------------------------------------------------- #
# SmartRecruiters
# --------------------------------------------------------------------------- #
SR_POSTING = {
    "id": "744000012345",
    "name": "Software Engineer Intern",
    "releasedDate": "2026-09-01T10:00:00.000Z",
    "location": {"city": "Santa Clara", "region": "CA", "country": "us"},
}


def test_smartrecruiters_parses_a_posting(monkeypatch):
    monkeypatch.setattr(ats2.http, "get",
                        lambda *a, **k: FakeResponse({"totalFound": 1, "content": [SR_POSTING]}))
    jobs = ats2.fetch_smartrecruiters(company("smartrecruiters", id="PaloAltoNetworks2"))

    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "744000012345"
    assert j.title == "Software Engineer Intern"
    assert j.location == "Santa Clara, CA, us"
    assert j.url == "https://jobs.smartrecruiters.com/PaloAltoNetworks2/744000012345"
    assert j.posted_at == "2026-09-01T10:00:00.000Z"


def test_smartrecruiters_paginates(monkeypatch):
    pages = [
        {"totalFound": 150, "content": [dict(SR_POSTING, id=str(i)) for i in range(100)]},
        {"totalFound": 150, "content": [dict(SR_POSTING, id=str(i)) for i in range(100, 150)]},
        {"totalFound": 150, "content": []},
    ]
    calls = []

    def fake_get(url, **kw):
        calls.append(kw["params"]["offset"])
        return FakeResponse(pages[min(len(calls) - 1, len(pages) - 1)])

    monkeypatch.setattr(ats2.http, "get", fake_get)
    jobs = ats2.fetch_smartrecruiters(company("smartrecruiters", id="Acme"))
    assert len(jobs) == 150
    assert calls[:2] == [0, 100]


def test_smartrecruiters_remote_posting_gets_a_location(monkeypatch):
    """An empty location string reads as "unknown" to the geo filter. A posting
    the board explicitly marks remote should say Remote instead."""
    posting = {"id": "1", "name": "SWE Intern", "location": {"remote": True}}
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"content": [posting]}))
    jobs = ats2.fetch_smartrecruiters(company("smartrecruiters", id="Acme"))
    assert jobs[0].location == "Remote"


def test_smartrecruiters_skips_posting_without_an_id(monkeypatch):
    payload = {"content": [{"name": "No id here"}, SR_POSTING]}
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse(payload))
    assert len(ats2.fetch_smartrecruiters(company("smartrecruiters", id="Acme"))) == 1


def test_smartrecruiters_requires_an_id():
    with pytest.raises(ValueError, match="smartrecruiters"):
        ats2.fetch_smartrecruiters(company("smartrecruiters"))


# --------------------------------------------------------------------------- #
# Workable
# --------------------------------------------------------------------------- #
WORKABLE_JOB = {
    "title": "Software Engineer Intern",
    "shortcode": "ABC123DEF",
    "location": {"city": "Boston", "region": "Massachusetts", "country": "United States"},
    "url": "https://apply.workable.com/acme/j/ABC123DEF/",
    "published_on": "2026-09-01",
}


def test_workable_parses_a_job(monkeypatch):
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"jobs": [WORKABLE_JOB]}))
    jobs = ats2.fetch_workable(company("workable", slug="acme"))

    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "ABC123DEF"
    assert j.location == "Boston, Massachusetts, United States"
    assert j.url == "https://apply.workable.com/acme/j/ABC123DEF/"


def test_workable_builds_a_url_when_the_payload_omits_one(monkeypatch):
    job = {k: v for k, v in WORKABLE_JOB.items() if k != "url"}
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"jobs": [job]}))
    jobs = ats2.fetch_workable(company("workable", slug="acme"))
    assert jobs[0].url == "https://apply.workable.com/acme/j/ABC123DEF/"


def test_workable_handles_a_plain_string_location(monkeypatch):
    """Some tenants return a flat string rather than the structured object."""
    job = dict(WORKABLE_JOB, location="Remote, United States")
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"jobs": [job]}))
    jobs = ats2.fetch_workable(company("workable", slug="acme"))
    assert jobs[0].location == "Remote, United States"


def test_workable_empty_board(monkeypatch):
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"jobs": []}))
    assert ats2.fetch_workable(company("workable", slug="acme")) == []


def test_workable_requires_a_slug():
    with pytest.raises(ValueError, match="workable"):
        ats2.fetch_workable(company("workable"))


# --------------------------------------------------------------------------- #
# Recruitee
# --------------------------------------------------------------------------- #
RECRUITEE_OFFER = {
    "id": 998877,
    "title": "Software Engineer Intern",
    "slug": "software-engineer-intern",
    "careers_url": "https://acme.recruitee.com/o/software-engineer-intern",
    "city": "Toronto",
    "state_code": "ON",
    "country_code": "CA",
    "published_at": "2026-09-01T09:00:00.000Z",
}


def test_recruitee_parses_an_offer(monkeypatch):
    monkeypatch.setattr(ats2.http, "get",
                        lambda *a, **k: FakeResponse({"offers": [RECRUITEE_OFFER]}))
    jobs = ats2.fetch_recruitee(company("recruitee", slug="acme"))

    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "998877"
    assert j.location == "Toronto, ON, CA"
    assert j.url == "https://acme.recruitee.com/o/software-engineer-intern"


def test_recruitee_builds_a_url_when_missing(monkeypatch):
    offer = {k: v for k, v in RECRUITEE_OFFER.items() if k != "careers_url"}
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"offers": [offer]}))
    jobs = ats2.fetch_recruitee(company("recruitee", slug="acme"))
    assert jobs[0].url == "https://acme.recruitee.com/o/software-engineer-intern"


def test_recruitee_tolerates_null_location_fields(monkeypatch):
    """None must not become the string "None" in a location."""
    offer = dict(RECRUITEE_OFFER, city=None, state_code=None, country_code="CA")
    monkeypatch.setattr(ats2.http, "get", lambda *a, **k: FakeResponse({"offers": [offer]}))
    assert ats2.fetch_recruitee(company("recruitee", slug="acme"))[0].location == "CA"


def test_recruitee_requires_a_slug():
    with pytest.raises(ValueError, match="recruitee"):
        ats2.fetch_recruitee(company("recruitee"))


# --------------------------------------------------------------------------- #
# registry wiring
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["smartrecruiters", "workable", "recruitee"])
def test_adapter_is_registered(name):
    from jobscraper import adapters
    assert adapters.get(name) is not None
