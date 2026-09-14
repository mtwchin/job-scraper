"""Tests for SeenStore — the record of what has already been sent to Discord.

The failure mode these guard against is always the same one: state that gets
lost, or is written in a form a later version can't read, makes already-sent
jobs look new and re-sends them.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from jobscraper.models import Job
from jobscraper.state import SeenStore


def job(**kw) -> Job:
    base = dict(company="Stripe", job_id="1", title="Software Engineer Intern",
                url="https://example.com/jobs/1", location="Seattle, WA")
    base.update(kw)
    return Job(**base)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "seen.json"


# --------------------------------------------------------------------------- #
# basic identity
# --------------------------------------------------------------------------- #
def test_new_job_is_new_then_not(store_path):
    store = SeenStore(store_path)
    j = job()
    assert store.is_new(j)
    store.add(j)
    assert not store.is_new(j)


def test_same_job_from_another_source_is_not_new(store_path):
    """A posting mirrored by an aggregator carries a different uid but the same
    apply link. This is the double-post bug that motivated the url index."""
    store = SeenStore(store_path)
    direct = job(source="", job_id="74", url="https://boards.greenhouse.io/a/jobs/74")
    store.add(direct)

    mirror = job(source="simplify", job_id="simplify-abc",
                 url="https://boards.greenhouse.io/a/jobs/74?utm_source=simplify")
    assert mirror.uid != direct.uid
    assert not store.is_new(mirror)
    assert store.match(mirror) == "url"


def test_repost_under_new_id_caught_by_fingerprint(store_path):
    store = SeenStore(store_path)
    store.add(job(job_id="1", url="https://x.com/jobs/1"))
    repost = job(job_id="2", url="https://x.com/jobs/2")
    assert store.match(repost) == "fingerprint"
    assert store.is_new(repost, use_fingerprint=False)


def test_distinct_job_still_reported_new(store_path):
    store = SeenStore(store_path)
    store.add(job(job_id="1", url="https://x.com/jobs/1"))
    other = job(job_id="2", url="https://x.com/jobs/2", title="Data Engineer Intern")
    assert store.is_new(other)


# --------------------------------------------------------------------------- #
# persistence round-trip
# --------------------------------------------------------------------------- #
def test_round_trip_preserves_dedup_across_processes(store_path):
    store = SeenStore(store_path)
    store.add(job())
    store.save()

    reloaded = SeenStore(store_path)
    assert reloaded.existed
    assert not reloaded.is_new(job())
    # and the cross-source index survives the trip
    assert not reloaded.is_new(job(source="simplify", job_id="mirror"))


def test_save_is_a_noop_when_nothing_changed(store_path):
    store = SeenStore(store_path)
    store.add(job())
    assert store.save() is True
    assert store.save() is False          # nothing new to write
    assert store.save(force=True) is True


def test_legacy_store_is_readable_and_still_dedups(store_path):
    """A v1 file has no schema, no location, no seeded_sources. It must keep
    deduping — otherwise upgrading re-sends the entire back catalogue."""
    store_path.write_text(json.dumps({
        "updated_at": "2026-01-01T00:00:00+00:00",
        "count": 1,
        "jobs": {
            "stripe::1": {
                "title": "Software Engineer Intern",
                "company": "Stripe",
                "url": "https://example.com/jobs/1",
                "first_seen": "2026-01-01T00:00:00+00:00",
            }
        },
    }), encoding="utf-8")

    store = SeenStore(store_path)
    assert store.existed
    assert not store.is_new(job())                                     # by uid
    assert not store.is_new(job(source="simplify", job_id="mirror"))   # by url


def test_legacy_store_infers_its_sources(store_path):
    """Old records carry no explicit source, so it's recovered from the uid
    prefix. Getting this wrong would make long-used sources look brand new."""
    store_path.write_text(json.dumps({"jobs": {
        "stripe::1": {"url": "https://x.com/1"},
        "simplify:stripe::simplify-9": {"url": "https://x.com/9"},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    assert store.seeded_sources == {"", "simplify"}
    assert store.is_source_seeded("simplify")
    assert not store.is_source_seeded("vanshb03")


def test_locationless_legacy_record_does_not_suppress_new_jobs(store_path):
    """A v1 record has no location, so it cannot produce a trustworthy
    fingerprint. It must not swallow a genuinely different posting."""
    store_path.write_text(json.dumps({"jobs": {
        "amazon::1": {"title": "SDE Intern", "company": "Amazon", "url": "https://a.com/1"},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    assert store.is_new(Job(company="Amazon", job_id="2", title="SDE Intern",
                            url="https://a.com/2", location="Austin, TX"))


# --------------------------------------------------------------------------- #
# pruning
# --------------------------------------------------------------------------- #
def _aged(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def test_prune_drops_only_long_delisted_records(store_path):
    store_path.write_text(json.dumps({"jobs": {
        "old::delisted": {"url": "https://x.com/1", "last_seen": _aged(200)},
        "old::still-open": {"url": "https://x.com/2", "last_seen": _aged(1)},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    assert store.prune(120) == 1
    assert store.has_uid("old::still-open")
    assert not store.has_uid("old::delisted")


def test_prune_keeps_a_long_open_role_however_old(store_path):
    """Keyed on last_seen, not first_seen: a role open for a year is still on
    the boards, and dropping it would re-notify it."""
    store_path.write_text(json.dumps({"jobs": {
        "x::1": {"url": "https://x.com/1", "first_seen": _aged(365), "last_seen": _aged(0)},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    assert store.prune(120) == 0


def test_prune_disabled_by_zero(store_path):
    store_path.write_text(json.dumps({"jobs": {
        "x::1": {"url": "https://x.com/1", "last_seen": _aged(9999)},
    }}), encoding="utf-8")
    assert SeenStore(store_path).prune(0) == 0


def test_prune_rebuilds_indexes(store_path):
    """A pruned record must stop matching, or the index would keep suppressing
    a posting whose record is gone."""
    store_path.write_text(json.dumps({"jobs": {
        "x::1": {"company": "Stripe", "title": "Software Engineer Intern",
                 "url": "https://example.com/jobs/1", "location": "Seattle, WA",
                 "last_seen": _aged(200)},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    assert not store.is_new(job())
    store.prune(120)
    assert store.is_new(job())


# --------------------------------------------------------------------------- #
# merge — the push path
# --------------------------------------------------------------------------- #
def test_merge_unions_both_sides(tmp_path):
    """Used before pushing: the remote may hold records we never saw, and
    dropping them would re-notify those jobs."""
    ours = tmp_path / "ours.json"
    theirs = tmp_path / "theirs.json"
    theirs.write_text(json.dumps({
        "jobs": {"b::9": {"url": "https://x.com/9"}},
        "seeded_sources": ["simplify"],
        "simplify_all_seeded": True,
    }), encoding="utf-8")

    store = SeenStore(ours)
    store.add(job(job_id="7", url="https://x.com/7"))
    assert store.merge_from(theirs) == 1
    assert store.has_uid("b::9")
    assert store.has_uid(job(job_id="7").uid)
    assert "simplify" in store.seeded_sources
    assert store.simplify_all_seeded


def test_merge_keeps_our_version_of_a_shared_record(tmp_path):
    ours = tmp_path / "ours.json"
    theirs = tmp_path / "theirs.json"
    theirs.write_text(json.dumps(
        {"jobs": {"stripe::1": {"url": "https://x.com/stale", "title": "stale"}}}),
        encoding="utf-8")

    store = SeenStore(ours)
    store.add(job())
    assert store.merge_from(theirs) == 0


def test_merge_from_missing_or_corrupt_file_is_harmless(tmp_path):
    store = SeenStore(tmp_path / "ours.json")
    store.add(job())
    assert store.merge_from(tmp_path / "nope.json") == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert store.merge_from(bad) == 0
    assert not store.is_new(job())


# --------------------------------------------------------------------------- #
# touch
# --------------------------------------------------------------------------- #
def test_touch_marks_a_record_still_listed(store_path):
    store_path.write_text(json.dumps({"jobs": {
        "stripe::1": {"url": "https://x.com/1", "last_seen": _aged(200)},
    }}), encoding="utf-8")

    store = SeenStore(store_path)
    store.touch("stripe::1")
    assert store.prune(120) == 0      # no longer looks delisted


def test_touch_of_unknown_uid_is_harmless(store_path):
    store = SeenStore(store_path)
    store.touch("nope::1")
    assert len(store) == 0
