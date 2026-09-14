"""Tests for the community listings.json feeds.

The conditional-request path matters as much as the parsing: polling every
minute is only affordable because an unchanged feed costs a 304 and no body.
"""
from __future__ import annotations

import pytest

from jobscraper import settings
from jobscraper.sources import aggregators


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def listing(**kw):
    base = dict(id="1", company_name="Stripe", title="Software Engineer Intern",
                url="https://example.com/jobs/1", locations=["Seattle, WA"],
                active=True, is_visible=True, date_posted=1750000000)
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def clear_cache():
    aggregators._cache.clear()
    yield
    aggregators._cache.clear()


@pytest.fixture
def one_feed(monkeypatch):
    """Reduce the feed list to a single, pre-categorized feed."""
    monkeypatch.setattr(settings, "AGGREGATOR_FEEDS",
                        [("SimplifyJobs", "Repo", "dev", "intern", True)])
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(settings, "SIMPLIFY_ALL_ENABLED", True)
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"stripe"})


def test_etag_is_sent_on_the_second_poll(one_feed, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(kw.get("headers", {}))
        if len(calls) == 1:
            return FakeResponse(200, [listing(category="Software")], {"ETag": '"abc"'})
        return FakeResponse(304)

    monkeypatch.setattr(aggregators.http, "get", fake_get)

    curated, all_jobs, changed = aggregators.fetch_pair()
    assert changed is True and len(all_jobs) == 1
    assert "If-None-Match" not in calls[0]

    curated, all_jobs, changed = aggregators.fetch_pair()
    assert calls[1]["If-None-Match"] == '"abc"'
    # A 304 still yields the full listing set, from cache, without a re-download.
    assert changed is False and len(all_jobs) == 1


def test_304_without_a_cache_entry_is_not_treated_as_success(one_feed, monkeypatch):
    """A 304 we can't satisfy from cache is an error, not an empty feed —
    silently returning nothing would look like every job was delisted."""
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(304))
    with pytest.raises(Exception):
        aggregators.fetch_pair()


def test_inactive_and_hidden_listings_are_dropped(one_feed, monkeypatch):
    payload = [
        listing(id="1", category="Software"),
        listing(id="2", category="Software", active=False),
        listing(id="3", category="Software", is_visible=False),
    ]
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(200, payload))
    _curated, all_jobs, _ = aggregators.fetch_pair()
    assert len(all_jobs) == 1


def test_pre_categorized_feed_trusts_its_category(one_feed, monkeypatch):
    """'Systems Engineer Intern' isn't a title-match for software, but the feed
    says it's Software — that's the whole value of the category field."""
    payload = [
        listing(id="1", title="Systems Engineer Intern", category="Software"),
        listing(id="2", title="Marketing Intern", category="Marketing"),
    ]
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(200, payload))
    _curated, all_jobs, _ = aggregators.fetch_pair()
    assert [j.title for j in all_jobs] == ["Systems Engineer Intern"]


def test_uncategorized_feed_falls_back_to_title_matching(monkeypatch):
    monkeypatch.setattr(settings, "AGGREGATOR_FEEDS",
                        [("vanshb03", "Repo", "dev", "intern", False)])
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"stripe"})
    payload = [
        listing(id="1", title="Software Engineer Intern"),
        listing(id="2", title="Marketing Intern"),
    ]
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(200, payload))
    _curated, all_jobs, _ = aggregators.fetch_pair()
    assert [j.title for j in all_jobs] == ["Software Engineer Intern"]
    assert all_jobs[0].source == "vanshb03"


def test_curated_view_is_limited_to_tracked_companies(one_feed, monkeypatch):
    payload = [
        listing(id="1", company_name="Stripe", category="Software"),
        listing(id="2", company_name="Some Startup", category="Software"),
    ]
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(200, payload))
    curated, all_jobs, _ = aggregators.fetch_pair()
    assert [j.company for j in curated] == ["Stripe"]
    assert len(all_jobs) == 2


def test_company_aliases_are_resolved(one_feed, monkeypatch):
    """The feed says TikTok; companies.md says ByteDance."""
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"bytedance"})
    payload = [listing(company_name="TikTok", category="Software")]
    monkeypatch.setattr(aggregators.http, "get", lambda url, **kw: FakeResponse(200, payload))
    curated, _all, _ = aggregators.fetch_pair()
    assert len(curated) == 1


def test_one_failing_feed_does_not_sink_the_others(monkeypatch):
    monkeypatch.setattr(settings, "AGGREGATOR_FEEDS", [
        ("SimplifyJobs", "Good", "dev", "intern", True),
        ("SimplifyJobs", "Bad", "dev", "intern", True),
    ])
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"stripe"})

    def fake_get(url, **kw):
        if "Bad" in url:
            raise RuntimeError("boom")
        return FakeResponse(200, [listing(category="Software")])

    monkeypatch.setattr(aggregators.http, "get", fake_get)
    _curated, all_jobs, _ = aggregators.fetch_pair()
    assert len(all_jobs) == 1


def test_all_feeds_failing_raises(monkeypatch):
    """A total outage must surface as an error, not as "no jobs today"."""
    monkeypatch.setattr(settings, "AGGREGATOR_FEEDS",
                        [("SimplifyJobs", "Repo", "dev", "intern", True)])
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"stripe"})

    def boom(url, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(aggregators.http, "get", boom)
    with pytest.raises(RuntimeError):
        aggregators.fetch_pair()


def test_role_type_filter_skips_unwanted_feeds(monkeypatch):
    monkeypatch.setattr(settings, "AGGREGATOR_FEEDS",
                        [("SimplifyJobs", "NewGrad", "dev", "new_grad", True)])
    monkeypatch.setattr(settings, "ROLE_TYPES", {"intern"})
    monkeypatch.setattr(aggregators, "our_company_names", lambda: {"stripe"})

    def should_not_be_called(url, **kw):
        raise AssertionError("fetched a feed whose role type was filtered out")

    monkeypatch.setattr(aggregators.http, "get", should_not_be_called)
    curated, all_jobs, changed = aggregators.fetch_pair()
    assert (curated, all_jobs, changed) == ([], [], False)
