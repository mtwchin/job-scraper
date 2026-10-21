"""Tests for the collect/dispatch logic in main."""
from __future__ import annotations

import pytest

from jobscraper import main, settings
from jobscraper.models import Job
from jobscraper.state import SeenStore


def job(**kw) -> Job:
    base = dict(company="Stripe", job_id="1", title="Software Engineer Intern",
                url="https://example.com/jobs/1", location="Seattle, WA")
    base.update(kw)
    return Job(**base)


@pytest.fixture
def store(tmp_path):
    return SeenStore(tmp_path / "seen.json")


# --------------------------------------------------------------------------- #
# select_new
# --------------------------------------------------------------------------- #
def test_select_new_filters_already_sent(store):
    first = job(job_id="1", url="https://x.com/1")
    store.add(first)
    second = job(job_id="2", url="https://x.com/2", title="Data Engineer Intern")

    assert main.select_new(store, [first, second]) == [second]


def test_select_new_drops_cross_source_duplicate(store):
    """Both feeds describe one opening; only one of them may be sent."""
    store.add(job(source="", job_id="74", url="https://boards.greenhouse.io/a/jobs/74"))
    mirror = job(source="simplify", job_id="simplify-x",
                 url="https://boards.greenhouse.io/a/jobs/74?utm_source=simplify")
    assert main.select_new(store, [mirror]) == []


def test_select_new_touches_still_listed_jobs(store, monkeypatch):
    """Seeing a known posting again must refresh it, so pruning doesn't mistake
    a long-open role for a delisted one."""
    j = job()
    store.add(j)
    store._seen[j.uid]["last_seen"] = "2020-01-01T00:00:00+00:00"

    main.select_new(store, [j])
    assert store._seen[j.uid]["last_seen"] != "2020-01-01T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# _absorb_new_sources
# --------------------------------------------------------------------------- #
def test_new_source_backlog_is_absorbed_not_sent(store, monkeypatch):
    """Switching on a feed surfaces its whole back catalogue at once. Those are
    new to us, not newly posted, and must not be blasted to Discord."""
    monkeypatch.setattr(settings, "SEED_QUIETLY", True)
    store.mark_source_seeded("")          # direct adapters already established

    curated = [job(source="newfeed", job_id="a", url="https://x.com/a"),
               job(source="newfeed", job_id="b", url="https://x.com/b", title="SWE Intern")]
    general = []

    absorbed = main._absorb_new_sources(store, curated, general)

    assert absorbed == {"newfeed": 2}
    assert curated == []                                  # nothing left to send
    assert not store.is_new(job(source="newfeed", job_id="a", url="https://x.com/a"))
    assert store.is_source_seeded("newfeed")


def test_established_source_is_not_absorbed(store, monkeypatch):
    monkeypatch.setattr(settings, "SEED_QUIETLY", True)
    store.mark_source_seeded("simplify")

    curated = [job(source="simplify", job_id="a", url="https://x.com/a")]
    assert main._absorb_new_sources(store, curated) == {}
    assert len(curated) == 1                              # still sent


def test_absorb_is_skipped_when_quiet_seeding_is_off(store, monkeypatch):
    """Turning off quiet seeding means the operator asked for everything."""
    monkeypatch.setattr(settings, "SEED_QUIETLY", False)
    curated = [job(source="newfeed", job_id="a", url="https://x.com/a")]
    assert main._absorb_new_sources(store, curated) == {}
    assert len(curated) == 1


def test_absorb_only_touches_the_unseeded_source(store, monkeypatch):
    """A sweep mixes sources; adding one feed must not swallow another's jobs."""
    monkeypatch.setattr(settings, "SEED_QUIETLY", True)
    store.mark_source_seeded("simplify")

    known = job(source="simplify", job_id="k", url="https://x.com/k")
    fresh = job(source="newfeed", job_id="n", url="https://x.com/n", title="SWE Intern")
    bucket = [known, fresh]

    assert main._absorb_new_sources(store, bucket) == {"newfeed": 1}
    assert bucket == [known]


# --------------------------------------------------------------------------- #
# _passes_filters
# --------------------------------------------------------------------------- #
def test_job_without_url_is_rejected():
    assert not main._passes_filters(job(url=""))


def test_pre_categorized_source_skips_title_matching(monkeypatch):
    """Feeds that curate to software roles upstream are trusted, so titles like
    'Systems Engineer Intern' survive."""
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    listed = job(source="simplify", title="Quantitative Researcher Intern")
    assert main._passes_filters(listed)


def test_uncategorized_source_gets_title_matching(monkeypatch):
    """Feeds with no category field must be title-filtered, or they flood the
    channel with non-software roles."""
    monkeypatch.setattr(settings, "US_CANADA_ONLY", False)
    assert not main._passes_filters(job(source="vanshb03", title="Marketing Intern"))
    assert main._passes_filters(job(source="vanshb03", title="Software Engineer Intern"))


# --------------------------------------------------------------------------- #
# health alert
# --------------------------------------------------------------------------- #
def _sweep(failing: int, total: int = 10, adapter: str = "workday") -> main.Collection:
    outcomes = [(f"Co{i}", adapter, "[workday] NotJSON: HTTP 200 with an empty body" if i < failing
                 else None) for i in range(total)]
    return main.Collection(errors=[f"{n}: {e}" for n, _, e in outcomes if e],
                           outcomes=outcomes, n_enabled=total)


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(main.notify, "notify_summary", lambda msg, *a, **kw: sent.append(msg))
    return sent


def test_single_bad_sweep_does_not_alert(store, alerts):
    """One sweep where everything fails is usually the runner's network blinking."""
    main._maybe_health_alert(_sweep(9), store, min_sweeps=2, min_age=0)
    main._maybe_health_alert(_sweep(0), store, min_sweeps=2, min_age=0)
    main._maybe_health_alert(_sweep(9), store, min_sweeps=2, min_age=0)
    assert alerts == []


def test_sustained_errors_alert_once(store, alerts):
    for _ in range(4):
        main._maybe_health_alert(_sweep(9), store, min_sweeps=2, min_age=0)
    assert len(alerts) == 1
    assert "9 companies failing" in alerts[0]
    assert "workday" in alerts[0] and "empty body" in alerts[0]


def test_alert_waits_for_min_age(store, alerts):
    for _ in range(4):
        main._maybe_health_alert(_sweep(3), store, min_sweeps=2, min_age=600)
    assert alerts == []


def test_one_shot_run_alerts_on_first_sweep(store, alerts):
    main._maybe_health_alert(_sweep(9), store, min_sweeps=1, min_age=0)
    assert len(alerts) == 1


def test_mixed_sweep_sizes_do_not_repeat_the_alert(store, alerts):
    """The regression: a small priority sweep (5/19 failing) and a big full
    sweep (10/136 failing) alternated, and the low-rate full sweep counted as a
    recovery, re-arming the alert every few minutes."""
    def sweep(total, failing):
        outcomes = [(f"Co{i}", "workday" if i < 10 else "greenhouse",
                     "[workday] NotJSON" if i < failing else None) for i in range(total)]
        return main.Collection(errors=["x"] * failing, outcomes=outcomes, n_enabled=total)

    for _ in range(10):
        main._maybe_health_alert(sweep(5, 5), store, min_sweeps=2, min_age=0)
        main._maybe_health_alert(sweep(136, 10), store, min_sweeps=2, min_age=0)
    downs = [a for a in alerts if a.startswith("⚠️")]
    # Co0-4 go down together, Co5-9 (full sweep only) a sweep later — then silence.
    assert len(downs) == 2
    assert not any(a.startswith("✅") for a in alerts)


def test_recovery_is_announced_once(store, alerts):
    for _ in range(2):
        main._maybe_health_alert(_sweep(3), store, min_sweeps=2, min_age=0)
    main._maybe_health_alert(_sweep(0), store, min_sweeps=2, min_age=0)
    main._maybe_health_alert(_sweep(0), store, min_sweeps=2, min_age=0)
    assert len(alerts) == 2
    assert alerts[1].startswith("✅") and "Co0, Co1, Co2" in alerts[1]


def test_reported_outage_survives_a_new_process(tmp_path, alerts):
    """A fresh watch loop that starts mid-outage must not repeat the alert."""
    path = tmp_path / "seen.json"
    first = SeenStore(path)
    for _ in range(2):
        main._maybe_health_alert(_sweep(3), first, min_sweeps=2, min_age=0)
    second = SeenStore(path)
    for _ in range(3):
        main._maybe_health_alert(_sweep(3), second, min_sweeps=2, min_age=0)
    assert len(alerts) == 1


# --------------------------------------------------------------------------- #
# backoff
# --------------------------------------------------------------------------- #
def test_failing_board_backs_off_then_retries(monkeypatch):
    from jobscraper.models import CompanyConfig
    company = CompanyConfig("Nvidia", "workday", {})
    calls = []

    def fetch(c):
        calls.append(c.name)
        raise RuntimeError("throttled")

    monkeypatch.setattr(main, "load_companies", lambda _path: [company])
    monkeypatch.setattr(main.adapters, "get", lambda _name: fetch)
    monkeypatch.setattr(settings, "SIMPLIFY_ENABLED", False)
    clock = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])

    first, _ = main.collect_matches()
    assert len(first.errors) == 1
    skipped, _ = main.collect_matches()          # inside the 30s pause
    assert calls == ["Nvidia"] and skipped.n_backed_off == 1 and not skipped.errors
    clock[0] += 31
    main.collect_matches()                        # retried, fails again -> 60s
    clock[0] += 45
    main.collect_matches()
    assert calls == ["Nvidia", "Nvidia"]
    clock[0] += 20
    main.collect_matches()
    assert calls == ["Nvidia", "Nvidia", "Nvidia"]


# --------------------------------------------------------------------------- #
# SCOPE: the top / rest tiers run as separate workflows
# --------------------------------------------------------------------------- #
@pytest.fixture
def two_sources(monkeypatch):
    """One tracked company on its own board, plus a feed listing a tracked and
    an untracked company."""
    from jobscraper.models import CompanyConfig
    from jobscraper.sources import aggregators

    board_calls = []
    tracked = Job("Stripe", "1", "Software Engineer Intern", "https://stripe.example/1", "Seattle, WA")
    feed_tracked = Job("Stripe", "simplify-2", "Software Engineer Intern II",
                       "https://stripe.example/2", "Seattle, WA", source="simplify")
    feed_other = Job("Acme", "simplify-3", "Software Engineer Intern",
                     "https://acme.example/3", "Austin, TX", source="simplify")
    monkeypatch.setattr(main, "load_companies",
                        lambda _p: [CompanyConfig("Stripe", "greenhouse", {"token": "stripe"})])
    monkeypatch.setattr(main, "_fetch_company",
                        lambda c: board_calls.append(c.name) or (c, [tracked], None))
    monkeypatch.setattr(aggregators, "fetch_pair",
                        lambda: ([feed_tracked], [feed_tracked, feed_other], True))
    monkeypatch.setattr(main.settings, "SIMPLIFY_ENABLED", True)
    monkeypatch.setattr(main.settings, "DISCORD_WEBHOOK_URL_ALL", "https://example.test/all")
    monkeypatch.setattr(main.settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(main.settings, "US_CANADA_ONLY", False)
    return board_calls


def test_top_scope_alerts_tracked_companies_only(two_sources, monkeypatch):
    monkeypatch.setattr(main.settings, "SCOPE", "top")
    monkeypatch.setattr(main.settings, "SIMPLIFY_ALL_ENABLED", False)
    c, general = main.collect_matches()
    assert {j.company for j in c.matches} == {"Stripe"} and len(c.matches) == 2
    assert general.matches == []


def test_rest_scope_skips_boards_and_tracked_companies(two_sources, monkeypatch):
    monkeypatch.setattr(main.settings, "SCOPE", "rest")
    monkeypatch.setattr(main.settings, "SIMPLIFY_ALL_ENABLED", True)
    c, general = main.collect_matches(include_companies=True)
    assert two_sources == []                      # no board was fetched
    assert c.matches == []                        # tracked roles belong to `top`
    assert [j.company for j in general.matches] == ["Acme"]
