"""Webhook delivery persists a claim before the HTTP request."""
import json
import sys

import pytest
import requests
import urllib3

from jobscraper import cli, main, notify, settings
from jobscraper.models import Job
from jobscraper.state import SeenStore


def _job(i):
    return Job("Acme", str(i), f"Software Engineer Intern, Team {i}", f"https://example.test/jobs/{i}",
               "New York, NY")


def _ready_store(path):
    store = SeenStore(path)
    store.mark_source_seeded("")
    store.mark_simplify_all_seeded()
    store.save()
    return SeenStore(path)


def _collection(jobs):
    return main.Collection(matches=jobs), main.Collection()


def test_lost_webhook_response_is_not_replayed(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(notify.http, "post", lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout()))

    with pytest.raises(RuntimeError, match="Timeout"):
        main.dispatch(store, *_collection([posting]))

    reloaded = SeenStore(path)
    assert posting.uid in reloaded.delivery_attempts
    assert reloaded.match(posting) == "attempt"
    monkeypatch.setattr(notify.http, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("replayed")))
    assert main.dispatch(reloaded, *_collection([posting])) == 0


def test_rejected_webhook_can_retry(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(notify.http, "post", lambda *a, **kw: type("R", (), {"status_code": 400})())

    with pytest.raises(notify.WebhookRejected, match="HTTP 400"):
        main.dispatch(store, *_collection([posting]))
    reloaded = SeenStore(path)
    assert not reloaded.delivery_attempts
    assert reloaded.is_new(posting)


def _dns_failure(*a, **kw):
    reason = urllib3.exceptions.NameResolutionError("discord.com", None, "Temporary failure")
    raise requests.ConnectionError(urllib3.exceptions.MaxRetryError(None, "/", reason))


@pytest.mark.parametrize("error", [_dns_failure, requests.ConnectTimeout])
def test_unsent_webhook_request_is_retried(tmp_path, monkeypatch, error):
    """A request that never left the runner can't have posted anything, so it
    must not be parked as 'unknown outcome' — that would mean never sending it."""
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    if isinstance(error, type):
        monkeypatch.setattr(notify.http, "post", lambda *a, **kw: (_ for _ in ()).throw(error()))
    else:
        monkeypatch.setattr(notify.http, "post", error)

    with pytest.raises(notify.WebhookRejected, match="unreachable"):
        main.dispatch(store, *_collection([posting]))
    reloaded = SeenStore(path)
    assert not reloaded.delivery_attempts
    assert reloaded.is_new(posting)


def test_dropped_connection_after_send_stays_ambiguous(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    aborted = requests.ConnectionError(urllib3.exceptions.ProtocolError("Connection aborted."))
    monkeypatch.setattr(notify.http, "post", lambda *a, **kw: (_ for _ in ()).throw(aborted))

    with pytest.raises(RuntimeError, match="request failed"):
        main.dispatch(store, *_collection([posting]))
    assert posting.uid in SeenStore(path).delivery_attempts


def test_successful_first_batch_persists_before_second_times_out(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    postings = [_job(i) for i in range(11)]
    calls = 0

    def post(*a, **kw):
        nonlocal calls
        calls += 1
        return type("R", (), {"status_code": 204 if calls == 1 else 500})()

    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(notify.http, "post", post)
    monkeypatch.setattr(notify.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        main.dispatch(store, *_collection(postings))
    reloaded = SeenStore(path)
    assert all(reloaded.has_uid(j.uid) for j in postings[:10])
    assert postings[10].uid in reloaded.delivery_attempts


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot read"):
        SeenStore(path)


def test_merge_preserves_remote_attempt(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    posting = _job(1)
    local_store = _ready_store(local)
    remote_store = _ready_store(remote)
    remote_store.begin_delivery([posting])
    assert local_store.merge_from(remote) == 0
    local_store.save()
    assert SeenStore(local).match(posting) == "attempt"


def test_rejected_attempt_is_not_restored_by_older_checkpoint(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    posting = _job(1)
    store = _ready_store(local)
    store.begin_delivery([posting])
    remote.write_bytes(local.read_bytes())
    store.reject_delivery([posting])
    store.merge_from(remote)
    store.save()
    assert SeenStore(local).is_new(posting)


def test_save_unions_disk_records_added_by_checkpoint_process(tmp_path):
    path = tmp_path / "state.json"
    watch_store = _ready_store(path)
    checkpoint_store = SeenStore(path)
    checkpoint_store.add(_job(1))
    checkpoint_store.save()
    watch_store.add(_job(2))
    watch_store.save()
    reloaded = SeenStore(path)
    assert reloaded.has_uid(_job(1).uid)
    assert reloaded.has_uid(_job(2).uid)


def test_pruned_record_is_not_restored_by_state_merge(tmp_path):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    store.add(posting)
    store._seen[posting.uid]["last_seen"] = "2020-01-01T00:00:00+00:00"
    store.save()
    old_copy = tmp_path / "old.json"
    old_copy.write_bytes(path.read_bytes())
    assert store.prune(120) == 1
    store.save()
    assert not SeenStore(path).has_uid(posting.uid)
    store.merge_from(old_copy)
    store.save()
    assert not SeenStore(path).has_uid(posting.uid)


def _sent_payloads(monkeypatch):
    payloads = []

    def post(_url, json=None, **kw):
        payloads.append(json)
        return type("R", (), {"status_code": 204})()

    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(notify.http, "post", post)
    monkeypatch.setattr(notify.time, "sleep", lambda _: None)
    return payloads


def _office(i, city):
    return Job("Harvey", f"req-{i}", "Software Engineering Intern (Summer 2027)",
               f"https://example.test/jobs/{i}", city)


def test_same_title_in_several_offices_is_one_alert(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    payloads = _sent_payloads(monkeypatch)
    ny, sf = _office(1, "New York"), _office(2, "San Francisco")

    assert main.dispatch(store, *_collection([ny, sf])) == 1
    [embed] = payloads[0]["embeds"]
    assert embed["fields"][0]["value"] == "New York; San Francisco"
    reloaded = SeenStore(path)
    assert reloaded.has_uid(ny.uid) and reloaded.has_uid(sf.uid)
    # The folded copy is recorded as quiet, so the freshness audit skips it.
    assert reloaded._seen[sf.uid]["duplicate_of"] == ny.uid


def test_same_title_relisted_within_cooldown_is_suppressed(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    payloads = _sent_payloads(monkeypatch)

    main.dispatch(store, *_collection([_office(1, "New York")]))
    # A later sweep — even a new process reading the file back — sees the same
    # role re-listed in another city.
    store = SeenStore(path)
    assert main.dispatch(store, *_collection([_office(3, "Austin")])) == 0
    assert len(payloads) == 1
    # Recorded, so it stays quiet after the cooldown expires too.
    assert SeenStore(path).has_uid(_office(3, "Austin").uid)


def test_title_cooldown_expires(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    payloads = _sent_payloads(monkeypatch)
    main.dispatch(store, *_collection([_office(1, "New York")]))

    # Backdate the alert to just outside the default 7-day window.
    data = json.loads(path.read_text())
    data["jobs"][_office(1, "New York").uid]["first_seen"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(data))
    assert main.dispatch(SeenStore(path), *_collection([_office(3, "Austin")])) == 1
    assert len(payloads) == 2


def test_title_cooldown_can_be_disabled(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    _sent_payloads(monkeypatch)
    monkeypatch.setattr(settings, "TITLE_COOLDOWN_HOURS", 0)
    assert main.dispatch(store, *_collection([_office(1, "New York"), _office(2, "Austin")])) == 2


def _age_attempt(path, uid, attempted_at="2020-01-01T00:00:00+00:00"):
    data = json.loads(path.read_text(encoding="utf-8"))
    data["delivery_attempts"][uid]["attempted_at"] = attempted_at
    path.write_text(json.dumps(data), encoding="utf-8")


def test_stale_attempt_is_settled_as_delivered_and_stays_deduped(tmp_path, monkeypatch):
    """An unknown outcome can never confirm itself, so after the review window
    it is recorded as sent: still never re-sent, but no longer pending."""
    path = tmp_path / "state.json"
    store = _ready_store(path)
    posting = _job(1)
    store.begin_delivery([posting])
    _age_attempt(path, posting.uid)
    store = SeenStore(path)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(notify.http, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("replayed")))

    assert main.dispatch(store, *_collection([posting])) == 0
    reloaded = SeenStore(path)
    assert not reloaded.delivery_attempts
    assert reloaded.match(posting) == "uid"
    assert reloaded._seen[posting.uid]["delivery_unconfirmed"] is True
    assert reloaded._seen[posting.uid]["first_seen"] == "2020-01-01T00:00:00+00:00"


def test_recent_attempt_waits_for_review_window(tmp_path):
    store = _ready_store(tmp_path / "state.json")
    store.begin_delivery([_job(1)])
    assert store.settle_stale_attempts(24) == []
    assert store.settle_stale_attempts(0) == []
    assert _job(1).uid in store.delivery_attempts


def test_settled_attempt_is_not_restored_by_older_checkpoint(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    posting = _job(1)
    store = _ready_store(local)
    store.begin_delivery([posting])
    remote.write_bytes(local.read_bytes())
    store.settle_attempt(posting.uid)
    store.merge_from(remote)
    store.save()
    assert not SeenStore(local).delivery_attempts


def test_retry_resolved_by_cli_sticks_against_running_loop(tmp_path, monkeypatch):
    """The watch loop holds the attempt in memory. A retry made from the CLI
    meanwhile must win when the loop next saves, or it is written straight back."""
    path = tmp_path / "state.json"
    loop_store = _ready_store(path)
    posting = _job(1)
    loop_store.begin_delivery([posting])
    monkeypatch.setattr(settings, "STATE_FILE", path)
    monkeypatch.setattr(sys, "argv", ["jobscraper", "delivery-status", "--retry", posting.uid])
    assert cli.main() == 0

    loop_store.add(_job(2))  # any later save by the loop
    loop_store.save()
    reloaded = SeenStore(path)
    assert not reloaded.delivery_attempts
    assert reloaded.is_new(posting)


def test_cli_settle_all(tmp_path, monkeypatch, capsys):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    store.begin_delivery([_job(1), _job(2)])
    monkeypatch.setattr(settings, "STATE_FILE", path)
    monkeypatch.setattr(sys, "argv", ["jobscraper", "delivery-status"])
    assert cli.main() == 1
    assert "2 webhook attempt(s)" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["jobscraper", "delivery-status", "--settle", "--all"])
    assert cli.main() == 0
    reloaded = SeenStore(path)
    assert not reloaded.delivery_attempts
    assert reloaded.has_uid(_job(1).uid) and reloaded.has_uid(_job(2).uid)


def test_pending_attempt_warns_once_not_every_sweep(tmp_path, monkeypatch, caplog):
    path = tmp_path / "state.json"
    store = _ready_store(path)
    store.begin_delivery([_job(1)])
    monkeypatch.setattr(settings, "DRY_RUN", False)
    for _ in range(3):
        main.dispatch(store, *_collection([]))
    assert sum("unknown outcomes" in r.message for r in caplog.records) == 1
    store.begin_delivery([_job(2)])
    main.dispatch(store, *_collection([]))
    assert sum("unknown outcomes" in r.message for r in caplog.records) == 2
