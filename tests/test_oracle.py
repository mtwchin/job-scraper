"""Oracle search must page through the board, including older requisitions."""
import pytest

from jobscraper.adapters import oracle
from jobscraper.models import CompanyConfig


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_fetch_paginates_and_keeps_older_requisitions(monkeypatch):
    calls = []

    def get(url, **kwargs):
        finder = kwargs["params"]["finder"]
        calls.append(finder)
        if "offset=0" in finder:
            rows = [
                {"Id": 123, "Title": "Software Engineer Intern", "PostedDate": "2026-09-22",
                 "PrimaryLocation": "New York, NY, United States",
                 "secondaryLocations": [{"Name": "Toronto, ON, Canada"}]},
                {"Id": 124, "Title": "Other", "PostedDate": "2026-09-22",
                 "PrimaryLocation": "London, United Kingdom"},
            ]
        else:
            rows = [{"Id": 125, "Title": "Older role newly made visible",
                     "PostedDate": "2026-08-01", "PrimaryLocation": "Seattle, WA"}]
        return Response({"items": [{"TotalJobsCount": 3, "requisitionList": rows}]})

    monkeypatch.setattr(oracle.http, "get", get)
    jobs = oracle.fetch(CompanyConfig("JPMC", "oracle", {
        "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"}))
    assert [j.job_id for j in jobs] == ["123", "124", "125"]
    assert jobs[0].location == "New York, NY, United States; Toronto, ON, Canada"
    assert jobs[0].url.endswith("/sites/CX_1001/job/123/")
    assert len(calls) == 2
    assert "offset=2" in calls[1]


def test_missing_requisitions_is_error(monkeypatch):
    monkeypatch.setattr(oracle.http, "get", lambda *a, **kw: Response({
        "items": [{"TotalJobsCount": 3}]}))
    with pytest.raises(ValueError, match="omitted requisitions"):
        oracle.fetch(CompanyConfig("JPMC", "oracle", {
            "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"}))
