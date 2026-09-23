"""Major-company sweeps use the configured subset between full scans."""
from jobscraper import main, settings
from jobscraper.models import CompanyConfig


def test_priority_collection_fetches_only_selected_companies(monkeypatch):
    companies = [CompanyConfig("Apple", "apple"), CompanyConfig("JPMC", "oracle")]
    fetched = []
    monkeypatch.setattr(main, "load_companies", lambda path: companies)
    monkeypatch.setattr(settings, "PRIORITY_COMPANIES", {"apple"})
    monkeypatch.setattr(main, "_fetch_company", lambda c: (fetched.append(c.name) or (c, [], None)))
    monkeypatch.setattr(main, "_collect_aggregators", lambda *a, **kw: False)
    curated, _ = main.collect_matches(only_priority=True)
    assert fetched == ["Apple"]
    assert curated.n_enabled == 1
