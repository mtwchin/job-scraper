"""Webhook delivery persists a claim before the HTTP request."""
import pytest
import requests

from jobscraper import main, notify, settings
from jobscraper.models import Job
from jobscraper.state import SeenStore


def _job(i):
    return Job("Acme", str(i), "Software Engineer Intern", f"https://example.test/jobs/{i}",
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
