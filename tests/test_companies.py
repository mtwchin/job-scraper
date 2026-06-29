"""Tests for companies.md parsing and that every enabled row is valid."""
from jobscraper import adapters, settings
from jobscraper.companies import load_companies


def test_companies_parse():
    companies = load_companies(settings.COMPANIES_FILE)
    assert len(companies) > 50  # sanity: the table loaded


def test_every_enabled_company_has_known_adapter_and_config():
    """A misconfigured enabled row would silently error every run — catch it here."""
    problems = []
    for c in load_companies(settings.COMPANIES_FILE):
        if not c.enabled:
            continue
        if adapters.get(c.adapter) is None:
            problems.append(f"{c.name}: unknown adapter '{c.adapter}'")
            continue
        if c.adapter in {"greenhouse", "lever", "ashby"} and not c.params:
            problems.append(f"{c.name}: {c.adapter} requires a token/slug")
        if c.adapter == "workday" and not all(
            k in c.params for k in ("host", "tenant", "site")
        ):
            problems.append(f"{c.name}: workday requires host/tenant/site")
    assert not problems, "\n".join(problems)


def test_no_duplicate_companies():
    names = [c.name.lower() for c in load_companies(settings.COMPANIES_FILE)]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate company rows: {dupes}"
