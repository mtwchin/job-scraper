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
