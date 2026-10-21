"""The watch loop's background company sweeps."""
from __future__ import annotations

import threading

from jobscraper import main, watch


def test_board_sweep_runs_beside_the_feed_poll_and_is_dispatched(monkeypatch):
    release = threading.Event()
    calls, dispatched = [], []

    def collect(**kw):
        calls.append(kw)
        release.wait(5)
        return main.Collection(n_enabled=1), main.Collection()

    monkeypatch.setattr(main, "collect_matches", collect)
    monkeypatch.setattr(main, "dispatch", lambda store, c, g: dispatched.append(c) or 3)
    stats = watch.Stats()
    boards = watch._Boards(store=None, stats=stats, company_interval=120, priority_interval=60)

    boards.tick()                      # starts a full sweep in the background
    assert calls == [{"include_companies": True, "only_priority": False,
                      "include_aggregators": False}]
    boards.tick()                      # still running: neither blocks nor restarts
    assert len(calls) == 1 and not dispatched

    release.set()
    boards.finish()
    assert len(dispatched) == 1 and stats.sent == 3 and stats.company_sweeps == 1


def test_priority_sweep_runs_between_full_sweeps(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "collect_matches",
                        lambda **kw: calls.append(kw) or (main.Collection(), main.Collection()))
    monkeypatch.setattr(main, "dispatch", lambda *a: 0)
    boards = watch._Boards(store=None, stats=watch.Stats(), company_interval=120,
                           priority_interval=60)
    boards.tick()
    boards.future.result()
    boards.next_priority = 0           # priority due, full sweep not
    boards.tick()
    boards.finish()
    assert [c["only_priority"] for c in calls] == [False, True]
