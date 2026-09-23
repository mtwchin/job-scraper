"""Microsoft's current public careers API shape and pagination."""
from jobscraper.adapters import microsoft
from jobscraper.models import CompanyConfig


class Response:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_uses_current_search_and_deduplicates_levels(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/careers"):
            return Response(text='<meta name="_csrf" content="token">')
        params = kwargs["params"]
        assert kwargs["headers"]["X-CSRF-Token"] == "token"
        assert params["filter_profession"] == "software engineering"
        if params["filter_seniority"] == "Intern":
            positions = [{"id": 123, "name": "Software Engineer Intern",
                          "positionUrl": "/careers/job/123",
                          "locations": ["United States, Washington, Redmond"],
                          "postedTs": 1790122300}]
        else:
            positions = [{"id": 123, "name": "Software Engineer Intern",
                          "positionUrl": "/careers/job/123",
                          "locations": ["United States, Washington, Redmond"],
                          "postedTs": 1790122300}]
        return Response(payload={"status": 200, "data": {"positions": positions, "count": 1}})

    monkeypatch.setattr(microsoft.http, "get", get)
    jobs = microsoft.fetch(CompanyConfig("Microsoft", "microsoft"))
    assert len(jobs) == 1
    assert jobs[0].url == "https://apply.careers.microsoft.com/careers/job/123"
    assert jobs[0].posted_at == "1790122300"
    assert len(calls) == 3


def test_missing_csrf_is_error(monkeypatch):
    monkeypatch.setattr(microsoft.http, "get", lambda *a, **kw: Response(text="<html>blocked</html>"))
    try:
        microsoft.fetch(CompanyConfig("Microsoft", "microsoft"))
    except ValueError as exc:
        assert "CSRF" in str(exc)
    else:
        assert False, "blocked page must not look like an empty job board"
