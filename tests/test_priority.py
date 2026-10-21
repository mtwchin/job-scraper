"""Priority (FAANG+) companies: quick sweeps of their own, and alerts first."""
from jobscraper import main, notify, settings
from jobscraper.models import CompanyConfig, Job
from jobscraper.state import SeenStore


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


def test_priority_sweep_is_quick_and_full_sweep_is_not(monkeypatch):
    companies = [CompanyConfig("Nvidia", "workday"), CompanyConfig("JPMC", "oracle")]
    fetched = []
    monkeypatch.setattr(main, "load_companies", lambda path: companies)
    monkeypatch.setattr(settings, "PRIORITY_COMPANIES", {"nvidia"})
    monkeypatch.setattr(main, "_fetch_company", lambda c: (fetched.append(c) or (c, [], None)))
    monkeypatch.setattr(main, "_collect_aggregators", lambda *a, **kw: False)
    main.collect_matches(only_priority=True)
    assert [(c.name, c.quick) for c in fetched] == [("Nvidia", True)]
    fetched.clear()
    main.collect_matches()
    assert sorted((c.name, c.quick) for c in fetched) == [("JPMC", False), ("Nvidia", False)]


# --- alerts --------------------------------------------------------------------


def _job(company, n=0, source=""):
    return Job(company=company, job_id=f"{company}-{n}", title="Software Engineer Intern",
               url=f"https://example.com/{company}/{n}", source=source)


def _capture(monkeypatch, mention=""):
    sent = []
    monkeypatch.setattr(settings, "PRIORITY_COMPANIES", {"google", "nvidia"})
    monkeypatch.setattr(settings, "PRIORITY_MENTION", mention)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(notify, "_post", lambda payload, url: sent.append(payload))
    monkeypatch.setattr(notify.time, "sleep", lambda _s: None)
    return sent


def test_priority_roles_go_first_in_their_own_pinging_batch(monkeypatch):
    sent = _capture(monkeypatch, mention="<@&123>")
    jobs = [_job("Stripe"), _job("Google"), _job("Ramp"), _job("NVIDIA", source="simplify")]
    notify.notify_jobs(jobs, webhook_url="https://discord.invalid/hook")
    assert len(sent) == 2
    top, rest = sent
    assert top["content"].startswith("<@&123> ⭐ **2 priority role(s)")
    assert [e["author"]["name"] for e in top["embeds"]] == ["⭐ Google", "⭐ NVIDIA"]
    assert "content" not in rest       # the rest never ping
    assert [e["author"]["name"] for e in rest["embeds"]] == ["Stripe", "Ramp"]


def test_without_priority_roles_messages_are_unchanged(monkeypatch):
    sent = _capture(monkeypatch, mention="@here")
    notify.notify_jobs([_job("Stripe"), _job("Ramp")], webhook_url="https://discord.invalid/hook")
    assert sent[0]["content"] == "🚨 **2 new role(s) just opened**"
    assert "@here" not in str(sent)


def test_priority_roles_are_not_held_back_by_the_run_cap(monkeypatch, tmp_path):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(settings, "MAX_NOTIFICATIONS_PER_RUN", 2)
    monkeypatch.setattr(settings, "SEED_QUIETLY", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.invalid/hook")
    monkeypatch.setattr(main, "_maybe_health_alert", lambda *a, **kw: None)
    store = SeenStore(tmp_path / "seen.json")
    store.existed = True
    jobs = [_job("Stripe", 1), _job("Ramp", 2), _job("Google", 3)]
    main.dispatch(store, main.Collection(matches=jobs), main.Collection())
    companies = [e["author"]["name"] for p in sent for e in p["embeds"]]
    assert companies[0] == "⭐ Google" and len(companies) == 2
