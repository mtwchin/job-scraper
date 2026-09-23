"""Workday's generic location labels must be resolved before US/CA filtering."""
import pytest

from jobscraper import filters, settings
from jobscraper.adapters import ats
from jobscraper.models import CompanyConfig


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.mark.parametrize("additional,expected", [
    (["Taiwan, Hsinchu"], False),
    (["United States, California, Santa Clara"], True),
])
def test_ambiguous_workday_location_uses_detail(additional, expected, monkeypatch):
    company = CompanyConfig("Nvidia", "workday", {
        "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia",
        "site": "NVIDIAExternalCareerSite",
    })
    posting = {"externalPath": "/job/Taiwan-Taipei/Software-Engineer-Intern_JR1",
               "title": "Software Engineer Intern", "locationsText": "2 Locations",
               "postedOn": "Posted Today"}
    monkeypatch.setattr(settings, "US_CANADA_ONLY", True)
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(ats.http, "post", lambda *a, **kw: Response({
        "jobPostings": [posting], "total": 1,
    }))
    detail_calls = []
    def detail(url, **kw):
        detail_calls.append(url)
        return Response({"jobPostingInfo": {
            "location": "Taiwan, Taipei", "additionalLocations": additional,
        }})
    monkeypatch.setattr(ats.http, "get", detail)
    jobs = ats.fetch_workday(company)
    assert len(jobs) == 1
    assert len(detail_calls) == 1
    assert filters.in_north_america(jobs[0].location) is expected
