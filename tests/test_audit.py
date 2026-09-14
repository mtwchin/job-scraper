"""Tests for the freshness audit.

The point of the audit is to answer "are we catching postings as they drop?"
honestly. The way it goes wrong is by counting things that were never alerts —
first-run backlog, a new source's back catalogue — as though they were, which
turns a healthy scraper into a 20-hour median.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from jobscraper import audit, settings
from jobscraper.models import Job
from jobscraper.state import SeenStore


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "seen.json"
    monkeypatch.setattr(settings, "STATE_FILE", path)
    return path


def ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def job(job_id: str, posted_minutes_ago: int, **kw) -> Job:
    base = dict(company="Stripe", title="Software Engineer Intern",
                url=f"https://example.com/jobs/{job_id}", location="Seattle, WA",
                posted_at=ago(posted_minutes_ago), source="")
    base.update(kw)
    return Job(job_id=job_id, **base)


def test_no_state_is_not_an_error(state, capsys):
    assert audit.main() == 0
    assert "No state yet" in capsys.readouterr().out


def test_seeded_records_are_excluded_from_latency(state, capsys):
    """A backlog entry was open before we started watching, so its "latency" is
    just its age. Counting it would make freshness look far worse than it is."""
    store = SeenStore(state)
    store.add(job("old", posted_minutes_ago=60 * 24 * 90), seeded=True)
    store.add(job("fresh", posted_minutes_ago=3))
    store.save()

    assert audit.main() == 0
    out = capsys.readouterr().out
    assert "1 alerted on, 1 absorbed quietly" in out
    # The 90-day backlog entry must not drag the percentages down.
    assert "caught within 5 minutes  : 1/1" in out


def test_reports_percentiles_over_alerted_records(state, capsys):
    store = SeenStore(state)
    for i, minutes in enumerate([1, 2, 3, 200]):
        store.add(job(f"j{i}", posted_minutes_ago=minutes))
    store.save()

    audit.main()
    out = capsys.readouterr().out
    assert "caught within 5 minutes  : 3/4" in out
    assert "caught within 24 hours   : 4/4" in out


def test_records_without_a_posting_time_are_counted_separately(state, capsys):
    """Dropping them silently would overstate confidence; averaging them in
    would invent a latency we don't know."""
    store = SeenStore(state)
    store.add(job("dated", posted_minutes_ago=5))
    store.add(job("undated", posted_minutes_ago=5, posted_at=""))
    store.save()

    audit.main()
    out = capsys.readouterr().out
    assert "1 had none" in out
    assert "caught within 5 minutes  : 1/1" in out


def test_per_source_breakdown_appears_with_multiple_sources(state, capsys):
    store = SeenStore(state)
    store.add(job("a", posted_minutes_ago=2, source=""))
    store.add(job("b", posted_minutes_ago=400, source="simplify"))
    store.save()

    audit.main()
    out = capsys.readouterr().out
    assert "By source" in out
    assert "simplify" in out
    assert "direct" in out


def test_legacy_store_is_flagged_as_unclassified(state, capsys):
    """A pre-upgrade store mixes backlog into the latency. The audit must say
    so, or the reader concludes freshness is terrible when it isn't measured."""
    state.write_text(json.dumps({"jobs": {
        "stripe::1": {"company": "Stripe", "title": "SWE Intern",
                      "url": "https://x.com/1", "posted_at": ago(60 * 24 * 200),
                      "first_seen": ago(1)},
    }}), encoding="utf-8")

    audit.main()
    out = capsys.readouterr().out
    assert "predate this audit's bookkeeping" in out


def test_current_store_is_not_flagged(state, capsys):
    store = SeenStore(state)
    store.add(job("a", posted_minutes_ago=2))
    store.save()

    audit.main()
    assert "predate this audit's bookkeeping" not in capsys.readouterr().out
