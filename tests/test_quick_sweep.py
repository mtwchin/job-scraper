"""Quick sweeps of every board, and one message format for every alert."""
from jobscraper import main, notify, settings
from jobscraper.models import CompanyConfig, Job
from jobscraper.sources import aggregators


def test_quick_sweep_covers_every_board_and_full_sweep_is_not_quick(monkeypatch):
    companies = [CompanyConfig("Nvidia", "workday"), CompanyConfig("Stripe", "greenhouse"),
                 CompanyConfig("Tesla", "custom", enabled=False)]
    fetched = []
    monkeypatch.setattr(main, "load_companies", lambda path: companies)
    monkeypatch.setattr(main, "_fetch_company", lambda c: (fetched.append(c) or (c, [], None)))
    monkeypatch.setattr(main, "_collect_aggregators", lambda *a, **kw: False)
    curated, _ = main.collect_matches(quick=True)
    assert sorted((c.name, c.quick) for c in fetched) == [("Nvidia", True), ("Stripe", True)]
    assert curated.n_enabled == 2
    fetched.clear()
    main.collect_matches()
    assert sorted((c.name, c.quick) for c in fetched) == [("Nvidia", False), ("Stripe", False)]


# --- alerts --------------------------------------------------------------------


def _job(company, n=0):
    return Job(company=company, job_id=f"{company}-{n}", title="Software Engineer Intern",
               url=f"https://example.com/{company}/{n}")


def test_every_message_has_the_same_header(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "MAX_EMBEDS_PER_MESSAGE", 2)
    monkeypatch.setattr(notify, "_post", lambda payload, url: sent.append(payload))
    monkeypatch.setattr(notify.time, "sleep", lambda _s: None)
    jobs = [_job("Google"), _job("Stripe"), _job("NVIDIA")]
    notify.notify_jobs(jobs, webhook_url="https://discord.invalid/hook")
    assert [p["content"] for p in sent] == ["🚨 **2 new role(s) just opened**",
                                            "🚨 **1 new role(s) just opened**"]
    assert [e["author"]["name"] for p in sent for e in p["embeds"]] == ["Google", "Stripe", "NVIDIA"]


# --- the FAANG+ list -----------------------------------------------------------


def test_companies_md_is_ibm_or_better_only():
    """Any row in companies.md, enabled or not, routes the feeds' copies of that
    company to the FAANG+ channel — which is how Disney got there. The bar is
    roughly IBM on the prestige ranking, or entry-level TC over $200K."""
    ours = aggregators.our_company_names()
    for name in ("Disney", "Barclays", "Accenture", "RTX", "Deloitte", "Infosys"):
        assert not aggregators._matches_company(name, ours), name
    for name in ("Google", "NVIDIA", "Meta Platforms", "TikTok", "Jane Street", "DE Shaw",
                 "IMC", "Uber Technologies, Inc.", "Anysphere", "IBM", "Oracle", "Red Hat",
                 "Susquehanna International Group", "Bridgewater Associates", "Square",
                 "Renaissance Technologies LLC", "The D. E. Shaw Group",
                 "JPMorgan Chase & Co.", "Capital One", "Cisco Systems", "Affirm",
                 "Zoom Video Communications", "Reddit, Inc.", "Instacart"):
        assert aggregators._matches_company(name, ours), name
