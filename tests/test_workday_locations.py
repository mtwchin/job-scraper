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


# --------------------------------------------------------------------------- #
# pagination, throttled responses, detail cache
# --------------------------------------------------------------------------- #
NVIDIA = CompanyConfig("Nvidia", "workday", {
    "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia",
    "site": "NVIDIAExternalCareerSite",
})


def _postings(offset, titles):
    return [{"externalPath": f"/job/US-CA-Santa-Clara/Role_JR{offset + i}", "title": t,
             "locationsText": "US, CA, Santa Clara", "postedOn": "Posted Today"}
            for i, t in enumerate(titles)]


@pytest.fixture
def one_query(monkeypatch):
    monkeypatch.setattr(ats, "_WORKDAY_QUERIES", ("software engineer intern",))
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    monkeypatch.setattr(ats.time, "sleep", lambda _s: None)


def test_pages_past_the_second_even_though_later_pages_report_total_zero(one_query, monkeypatch):
    """Workday sends `total` only on the first page; we used to stop at page 2."""
    def post(url, json, **kw):
        off = json["offset"]
        return Response({"total": 100 if off == 0 else 0,
                         "jobPostings": _postings(off, ["Software Engineer Intern"] * 20)})
    monkeypatch.setattr(ats.http, "post", post)
    assert len(ats.fetch_workday(NVIDIA)) == 100


def test_stops_after_consecutive_irrelevant_pages(one_query, monkeypatch):
    offsets = []
    def post(url, json, **kw):
        off = json["offset"]
        offsets.append(off)
        title = "Software Engineer Intern" if off == 0 else "Senior Staff Engineer"
        return Response({"total": 200 if off == 0 else 0, "jobPostings": _postings(off, [title] * 20)})
    monkeypatch.setattr(ats.http, "post", post)
    ats.fetch_workday(NVIDIA)
    assert offsets == [0, 20, 40]


def test_newest_first_pass_walks_every_today_page_then_stops(monkeypatch):
    """The empty search catches a new role whatever its title, without walking
    the board's whole back catalogue."""
    monkeypatch.setattr(ats, "_WORKDAY_QUERIES", ("",))
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    offsets = []
    def post(url, json, **kw):
        off = json["offset"]
        offsets.append(off)
        page = _postings(off, ["Compiler Engineer - New College Grad 2026"] * 20)
        if off == 40:
            page[-1]["postedOn"] = "Posted Yesterday"
        return Response({"total": 2000 if off == 0 else 0, "jobPostings": page})
    monkeypatch.setattr(ats.http, "post", post)
    assert len(ats.fetch_workday(NVIDIA)) == 60
    assert offsets == [0, 20, 40]


def test_newest_first_pass_is_capped(monkeypatch):
    monkeypatch.setattr(ats, "_WORKDAY_QUERIES", ("",))
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    offsets = []
    def post(url, json, **kw):
        offsets.append(json["offset"])
        return Response({"total": 2000, "jobPostings": _postings(json["offset"], ["Analyst"] * 20)})
    monkeypatch.setattr(ats.http, "post", post)
    ats.fetch_workday(NVIDIA)
    assert len(offsets) == ats._WORKDAY_NEWEST_PAGES


class Blocked:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    text = ""

    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_throttled_empty_body_is_retried_then_reported_clearly(one_query, monkeypatch):
    calls = []
    monkeypatch.setattr(ats.http, "post", lambda *a, **kw: calls.append(1) or Blocked())
    with pytest.raises(ats.http.NotJSON, match="empty body.*rate-limited"):
        ats.fetch_workday(NVIDIA)
    assert len(calls) == 2


def test_throttled_once_then_ok(one_query, monkeypatch):
    answers = [Blocked(), Response({"total": 1, "jobPostings": _postings(0, ["Software Engineer Intern"])})]
    monkeypatch.setattr(ats.http, "post", lambda *a, **kw: answers.pop(0))
    assert len(ats.fetch_workday(NVIDIA)) == 1


def test_detail_lookups_are_cached_across_sweeps(monkeypatch):
    monkeypatch.setattr(ats, "_WORKDAY_QUERIES", ("software engineer intern",))
    monkeypatch.setattr(settings, "US_CANADA_ONLY", True)
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    posting = {"externalPath": "/job/Taiwan-Taipei/Software-Engineer-Intern_JR1",
               "title": "Software Engineer Intern", "locationsText": "2 Locations"}
    monkeypatch.setattr(ats.http, "post", lambda *a, **kw: Response({"jobPostings": [posting], "total": 1}))
    detail_calls = []
    def detail(url, **kw):
        detail_calls.append(url)
        return Response({"jobPostingInfo": {"location": "US, CA, Santa Clara"}})
    monkeypatch.setattr(ats.http, "get", detail)
    for _ in range(3):
        assert ats.fetch_workday(NVIDIA)[0].location == "US, CA, Santa Clara"
    assert len(detail_calls) == 1
