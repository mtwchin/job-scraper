"""Workday's generic location labels must be resolved before US/CA filtering."""
from dataclasses import replace

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


def test_quick_sweep_runs_only_the_newest_first_pass(monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    queries = []
    def post(url, json, **kw):
        queries.append(json["searchText"])
        page = _postings(json["offset"], ["Software Engineer Intern"] * 20)
        page[-1]["postedOn"] = "Posted 3 Days Ago"
        return Response({"total": 2000, "jobPostings": page})
    monkeypatch.setattr(ats.http, "post", post)
    ats.fetch_workday(replace(NVIDIA, quick=True))
    assert queries == [""]
    queries.clear()
    ats.fetch_workday(NVIDIA)
    assert queries[0] == "" and len(set(queries)) == len(ats._WORKDAY_QUERIES)


class Blocked:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    text = ""

    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_throttled_empty_body_is_reported_clearly_and_not_retried(one_query, monkeypatch):
    calls = []
    monkeypatch.setattr(ats.http, "post", lambda *a, **kw: calls.append(1) or Blocked())
    with pytest.raises(ats.http.NotJSON, match="empty body.*rate-limited"):
        ats.fetch_workday(NVIDIA)
    assert len(calls) == 1


class Status(Response):
    def __init__(self, status_code, payload=None):
        super().__init__(payload or {})
        self.status_code = status_code


OK_PAGE = {"total": 1, "jobPostings": _postings(0, ["Software Engineer Intern"])}


@pytest.fixture
def clock(monkeypatch):
    """A fake monotonic clock that `sleep` advances, so pacing is observable."""
    now = [1000.0]
    monkeypatch.setattr(ats.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ats.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def test_a_429_is_not_retried_and_the_board_is_left_alone(one_query, clock, monkeypatch):
    """Every request during Workday's block restarts it, so a throttled board
    gets no request at all until its cooldown is over."""
    calls = []
    def post(url, **kw):
        calls.append(kw.get("retry_429"))
        return Status(429)
    monkeypatch.setattr(ats.http, "post", post)
    with pytest.raises(ats.WorkdayThrottled, match="429"):
        ats.fetch_workday(NVIDIA)
    assert calls == [False]                      # asked http not to retry it either
    with pytest.raises(ats.WorkdayThrottled, match="cooling down"):
        ats.fetch_workday(NVIDIA)
    assert len(calls) == 1                       # nothing was sent

    clock[0] += settings.WORKDAY_COOLDOWN_SECONDS + 1
    monkeypatch.setattr(ats.http, "post", lambda url, **kw: Status(200, OK_PAGE))
    assert len(ats.fetch_workday(NVIDIA)) == 1


def test_cooldown_doubles_while_the_board_keeps_refusing(one_query, clock, monkeypatch):
    monkeypatch.setattr(ats.http, "post", lambda url, **kw: Status(429))
    host = NVIDIA.params["host"]
    for expected in (240, 480, 960, 1800, 1800):
        with pytest.raises(ats.WorkdayThrottled):
            ats.fetch_workday(NVIDIA)
        assert ats.workday_cooling(host, clock[0] + expected - 1)
        assert not ats.workday_cooling(host, clock[0] + expected + 1)
        clock[0] += expected + 1


def test_success_resets_the_cooldown_length(one_query, clock, monkeypatch):
    answers = [Status(429), Status(200, OK_PAGE), Status(429)]
    monkeypatch.setattr(ats.http, "post", lambda url, **kw: answers.pop(0))
    host = NVIDIA.params["host"]
    with pytest.raises(ats.WorkdayThrottled):
        ats.fetch_workday(NVIDIA)
    clock[0] += 241
    ats.fetch_workday(NVIDIA)
    with pytest.raises(ats.WorkdayThrottled):
        ats.fetch_workday(NVIDIA)
    assert not ats.workday_cooling(host, clock[0] + 241)     # 240s again, not 480s


def test_several_boards_throttled_at_once_pauses_all_of_workday(one_query, clock, monkeypatch):
    """Workday limits by client IP: three boards refusing together means the
    rest would only be refused too, each request extending the block."""
    monkeypatch.setattr(ats.http, "post", lambda url, **kw: Status(429))
    for tenant in ("adobe", "zoom", "intel"):
        with pytest.raises(ats.WorkdayThrottled):
            ats.fetch_workday(CompanyConfig(tenant, "workday", {
                "host": f"{tenant}.wd5.myworkdayjobs.com", "tenant": tenant, "site": "x"}))
    assert ats.workday_cooling("nvidia.wd5.myworkdayjobs.com")
    clock[0] += 241
    assert not ats.workday_cooling("nvidia.wd5.myworkdayjobs.com")


def test_requests_to_one_board_are_spaced_apart(one_query, clock, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_MIN_GAP_SECONDS", 1.0)
    sent_at = []
    def post(url, json, **kw):
        sent_at.append(clock[0])
        return Status(200, {"total": 60, "jobPostings": _postings(
            json["offset"], ["Software Engineer Intern"] * 20)})
    monkeypatch.setattr(ats.http, "post", post)
    ats.fetch_workday(NVIDIA)
    ats.fetch_workday(replace(NVIDIA, quick=True))           # the other lane, same board
    assert len(sent_at) >= 4
    assert all(b - a >= 1.0 for a, b in zip(sent_at, sent_at[1:]))


def test_a_cooling_board_is_skipped_by_the_sweep_not_counted_as_failing(one_query, clock, monkeypatch):
    from jobscraper import main
    monkeypatch.setattr(main, "load_companies", lambda _path: [NVIDIA])
    monkeypatch.setattr(settings, "SIMPLIFY_ENABLED", False)
    monkeypatch.setattr(settings, "BACKOFF_BASE_SECONDS", 0)  # isolate the Workday cooldown
    calls = []
    monkeypatch.setattr(ats.http, "post", lambda url, **kw: calls.append(1) or Status(429))
    first, _ = main.collect_matches()
    assert len(first.errors) == 1
    for _ in range(5):                                        # 5 sweeps inside the cooldown
        clock[0] += 30
        skipped, _ = main.collect_matches()
        assert skipped.n_backed_off == 1 and not skipped.errors and not skipped.outcomes
    assert len(calls) == 1


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
