"""Google Careers company filtering used for DeepMind coverage."""
from jobscraper import settings
from jobscraper.adapters import google
from jobscraper.models import CompanyConfig


def test_company_filter_is_sent_to_google_careers(monkeypatch):
    params_seen = []

    def get(url, *, params):
        params_seen.append(params)
        return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr(google.http, "get", get)
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(settings, "US_CANADA_ONLY", True)
    assert google.fetch(CompanyConfig("DeepMind", "google", {"company": "DeepMind"})) == []
    assert len(params_seen) == 2
    assert all(p["company"] == "DeepMind" for p in params_seen)
