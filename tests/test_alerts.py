"""Tests for the operational alert sinks.

These exist because the sinks are the only thing standing between an outage and
silence now that health notices no longer go to Discord. The contract that
matters most is that none of them can break a sweep: a scraper that cannot file
a notice must still scrape.
"""
from __future__ import annotations

import json

import pytest

from jobscraper import alerts, health, settings
from jobscraper.state import SeenStore


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture
def gh_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    monkeypatch.setattr(settings, "HEALTH_ALERT_GITHUB", True)


@pytest.fixture
def calls(monkeypatch):
    """Record every GitHub API call the sink makes."""
    recorded = []

    def fake(method, url, token, payload=None):
        recorded.append((method, url, payload))
        if method == "GET":
            return FakeResponse(200, [])          # no existing issue
        return FakeResponse(201, {"number": 7})

    monkeypatch.setattr(alerts, "_gh_request", fake)
    return recorded


# --------------------------------------------------------------------------- #
# Actions annotations
# --------------------------------------------------------------------------- #
def test_annotation_is_emitted_in_actions(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    alerts._annotate("two boards down")
    assert "::warning::two boards down" in capsys.readouterr().out


def test_annotation_is_silent_outside_actions(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    alerts._annotate("two boards down")
    assert capsys.readouterr().out == ""


def test_multiline_annotation_is_escaped(monkeypatch, capsys):
    """A raw newline would terminate the workflow command and leave the rest of
    the notice as plain output, splitting one alert into two."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    alerts._annotate("line one\nline two\r100% down")
    out = capsys.readouterr().out
    assert "\n" not in out.rstrip("\n")
    assert "%0A" in out and "%0D" in out and "%25" in out


def test_step_summary_is_appended(monkeypatch, tmp_path):
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    alerts._step_summary("first")
    alerts._step_summary("second")
    body = path.read_text(encoding="utf-8")
    assert "first" in body and "second" in body


def test_step_summary_without_the_env_var_is_a_noop(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    alerts._step_summary("nothing to write to")   # must not raise


# --------------------------------------------------------------------------- #
# GitHub issue sink
# --------------------------------------------------------------------------- #
def test_opens_an_issue_when_none_exists(gh_env, calls):
    assert alerts._post_github_issue("workday is down", resolved=False) is True
    methods = [c[0] for c in calls]
    assert methods == ["GET", "POST"]
    created = calls[1][2]
    assert created["title"] == alerts.ISSUE_TITLE
    assert "workday is down" in created["body"]
    # The marker is what lets a later sweep find this issue again.
    assert alerts.ISSUE_MARKER in created["body"]


def test_comments_on_the_existing_issue_instead_of_opening_another(gh_env, monkeypatch):
    """One issue per outage, not one per sweep — this is what makes the sink
    safe to leave on by default."""
    recorded = []

    def fake(method, url, token, payload=None):
        recorded.append((method, url))
        if method == "GET":
            return FakeResponse(200, [{"number": 12, "state": "open",
                                       "body": "old\n" + alerts.ISSUE_MARKER}])
        return FakeResponse(201, {"number": 12})

    monkeypatch.setattr(alerts, "_gh_request", fake)
    alerts._post_github_issue("still down", resolved=False)
    assert recorded[1] == ("POST", alerts._api("/repos/owner/repo/issues/12/comments"))
    assert not any(m == "POST" and u.endswith("/issues") for m, u in recorded)


def test_a_closed_issue_is_reopened_for_a_new_outage(gh_env, monkeypatch):
    """A notice in a closed thread does not reach notifications."""
    recorded = []

    def fake(method, url, token, payload=None):
        recorded.append((method, url, payload))
        if method == "GET":
            return FakeResponse(200, [{"number": 12, "state": "closed",
                                       "body": alerts.ISSUE_MARKER}])
        return FakeResponse(200, {"number": 12})

    monkeypatch.setattr(alerts, "_gh_request", fake)
    alerts._post_github_issue("down again", resolved=False)
    patches = [c for c in recorded if c[0] == "PATCH"]
    assert patches and patches[0][2] == {"state": "open"}


def test_recovery_closes_the_issue(gh_env, monkeypatch):
    recorded = []

    def fake(method, url, token, payload=None):
        recorded.append((method, url, payload))
        if method == "GET":
            return FakeResponse(200, [{"number": 12, "state": "open",
                                       "body": alerts.ISSUE_MARKER}])
        return FakeResponse(200, {"number": 12})

    monkeypatch.setattr(alerts, "_gh_request", fake)
    alerts._post_github_issue("all recovered", resolved=True)
    patches = [c for c in recorded if c[0] == "PATCH"]
    assert patches and patches[0][2]["state"] == "closed"


def test_recovery_with_no_issue_files_nothing(gh_env, calls):
    """Nothing was ever reported, so there is nothing to close out."""
    assert alerts._post_github_issue("recovered", resolved=True) is False
    assert [c[0] for c in calls] == ["GET"]


def test_pull_requests_are_not_mistaken_for_the_issue(gh_env, monkeypatch):
    """The issues endpoint returns PRs too; commenting on a PR would be wrong."""
    def fake(method, url, token, payload=None):
        if method == "GET":
            return FakeResponse(200, [{"number": 3, "state": "open",
                                       "body": alerts.ISSUE_MARKER,
                                       "pull_request": {"url": "..."}}])
        return FakeResponse(201, {"number": 9})

    monkeypatch.setattr(alerts, "_gh_request", fake)
    alerts._post_github_issue("down", resolved=False)   # should open a fresh issue


@pytest.mark.parametrize("missing", ["GITHUB_TOKEN", "GITHUB_REPOSITORY"])
def test_without_credentials_the_sink_quietly_does_nothing(monkeypatch, missing):
    """It is on by default, so it has to no-op rather than error when the
    workflow has not granted it anything."""
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv(missing, raising=False)
    monkeypatch.delenv("HEALTH_ALERT_GITHUB_TOKEN", raising=False)
    assert alerts._post_github_issue("down", resolved=False) is False


def test_api_failure_is_swallowed(gh_env, monkeypatch):
    """A sweep must never die because an alert could not be filed."""
    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(alerts, "_gh_request", boom)
    assert alerts._post_github_issue("down", resolved=False) is False


def test_api_url_override_is_honoured(gh_env, monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3")
    assert alerts._api("/repos/x/y").startswith("https://ghe.example.com/api/v3/repos")


# --------------------------------------------------------------------------- #
# health_alert fan-out
# --------------------------------------------------------------------------- #
def test_health_alert_skips_github_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "HEALTH_ALERT_GITHUB", False)
    called = []
    monkeypatch.setattr(alerts, "_post_github_issue",
                        lambda *a, **kw: called.append(a))
    alerts.health_alert("down")
    assert called == []


def test_health_alert_reaches_every_enabled_sink(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    summary = tmp_path / "s.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(settings, "HEALTH_ALERT_GITHUB", True)
    filed = []
    monkeypatch.setattr(alerts, "_post_github_issue",
                        lambda text, resolved: filed.append((text, resolved)) or True)

    alerts.health_alert("two boards down")

    assert "::warning::two boards down" in capsys.readouterr().out
    assert "two boards down" in summary.read_text(encoding="utf-8")
    assert filed == [("two boards down", False)]


def test_recovery_annotates_at_notice_level(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(settings, "HEALTH_ALERT_GITHUB", False)
    alerts.health_alert("all clear", resolved=True)
    assert "::notice::all clear" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# on-demand snapshot
# --------------------------------------------------------------------------- #
def test_snapshot_reports_nothing_failing(tmp_path):
    store = SeenStore(tmp_path / "s.json")
    assert "No board is currently failing" in alerts.health_snapshot(store)


def test_snapshot_lists_failing_boards_with_streaks(tmp_path):
    store = SeenStore(tmp_path / "s.json")
    store.health.record("Stripe", "greenhouse", "[greenhouse] HTTPError: 503")
    store.health.record("Stripe", "greenhouse", "[greenhouse] HTTPError: 503")
    store.health_reported.add("Stripe")
    out = alerts.health_snapshot(store)
    assert "Stripe" in out and "greenhouse" in out
    assert "x2" in out and "[reported]" in out
    assert "503" in out


def test_snapshot_survives_a_process_boundary(tmp_path):
    """The whole reason the tracker is persisted: a loop restart must not make
    `jobscraper health` claim nothing is wrong mid-outage."""
    path = tmp_path / "s.json"
    first = SeenStore(path)
    first.health.record("Stripe", "greenhouse", "[greenhouse] HTTPError: 503")
    first.health.record("Stripe", "greenhouse", "[greenhouse] HTTPError: 503")
    first.save(force=True)

    second = SeenStore(path)
    assert "Stripe" in second.health.failing
    assert second.health.failing["Stripe"].streak == 2
    assert "Stripe" in alerts.health_snapshot(second)


def test_dump_json_is_parseable(tmp_path):
    store = SeenStore(tmp_path / "s.json")
    store.health.record("Stripe", "greenhouse", "boom")
    parsed = json.loads(alerts.dump_json(store))
    assert parsed["failing"]["Stripe"]["adapter"] == "greenhouse"


def test_malformed_persisted_health_is_skipped(tmp_path):
    """A hand-edited or truncated row must not take out the restore."""
    tracker = health.Tracker()
    tracker.load_dict({"Good": {"adapter": "ashby", "error": "x", "since": 1.0, "streak": 2},
                       "Bad": "not a dict",
                       "AlsoBad": {"adapter": "x", "since": "not a number"}})
    assert set(tracker.failing) == {"Good"}
