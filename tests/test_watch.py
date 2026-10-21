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

    boards.tick()                      # starts both lanes in the background
    assert sorted(c["only_priority"] for c in calls) == [False, True]
    assert all(c["include_companies"] and not c["include_aggregators"] for c in calls)
    boards.tick()                      # still running: neither blocks nor restarts
    assert len(calls) == 2 and not dispatched

    release.set()
    boards.finish()
    assert len(dispatched) == 2 and stats.sent == 6
    assert stats.company_sweeps == 1 and stats.priority_sweeps == 1


def test_priority_lane_never_waits_for_a_full_sweep(monkeypatch):
    """A slow full sweep used to hold the priority boards back to its own pace."""
    release = threading.Event()
    calls, dispatched = [], []

    def collect(**kw):
        calls.append(kw["only_priority"])
        if not kw["only_priority"]:
            release.wait(5)            # the full sweep is still running...
        return main.Collection(), main.Collection()

    monkeypatch.setattr(main, "collect_matches", collect)
    monkeypatch.setattr(main, "dispatch", lambda store, c, g: dispatched.append(c) or 0)
    boards = watch._Boards(store=None, stats=watch.Stats(), company_interval=120,
                           priority_interval=15)
    boards.tick()
    for _ in range(2):                 # ...while priority sweeps finish and repeat
        boards.priority.future.result()
        boards.priority.next_at = 0
        boards.tick()
    boards.priority.future.result()
    assert calls.count(True) == 3 and calls.count(False) == 1
    assert len(dispatched) == 2        # both finished priority sweeps, no full one yet

    release.set()
    boards.finish()
    assert len(dispatched) == 4
