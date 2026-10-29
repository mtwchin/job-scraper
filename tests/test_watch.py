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
        kw["on_board"](main.Collection(outcomes=[("Stripe", "greenhouse", None)]))
        return main.Collection(n_enabled=1), main.Collection()

    monkeypatch.setattr(main, "collect_matches", collect)
    monkeypatch.setattr(main, "dispatch", lambda store, c, g, **kw: dispatched.append(c) or 3)
    stats = watch.Stats()
    boards = watch._Boards(store=None, stats=stats, company_interval=120, quick_interval=60)

    boards.tick()                      # starts both lanes in the background
    assert sorted(c["quick"] for c in calls) == [False, True]
    assert all(c["include_companies"] and not c["include_aggregators"] for c in calls)
    boards.tick()                      # still running: neither blocks nor restarts
    assert len(calls) == 2 and not dispatched

    release.set()
    boards.finish()
    assert len(dispatched) == 2 and stats.sent == 6
    assert stats.company_sweeps == 1 and stats.quick_sweeps == 1


def test_quick_lane_never_waits_for_a_full_sweep(monkeypatch):
    """A slow full sweep used to hold the quick sweeps back to its own pace."""
    release = threading.Event()
    calls, dispatched = [], []

    def collect(**kw):
        calls.append(kw["quick"])
        if not kw["quick"]:
            release.wait(5)            # the full sweep is still running...
        kw["on_board"](main.Collection(outcomes=[("Stripe", "greenhouse", None)]))
        return main.Collection(), main.Collection()

    monkeypatch.setattr(main, "collect_matches", collect)
    monkeypatch.setattr(main, "dispatch", lambda store, c, g, **kw: dispatched.append(c) or 0)
    boards = watch._Boards(store=None, stats=watch.Stats(), company_interval=120,
                           quick_interval=15)
    boards.tick()
    for _ in range(2):                 # ...while quick sweeps finish and repeat
        boards.quick.future.result()
        boards.quick.next_at = 0
        boards.tick()
    boards.quick.future.result()
    assert calls.count(True) == 3 and calls.count(False) == 1
    assert len(dispatched) == 2        # both finished quick sweeps, no full one yet

    release.set()
    boards.finish()
    assert len(dispatched) == 4


def test_a_slow_board_does_not_hold_back_a_finished_one(monkeypatch):
    """A sweep used to report only once its slowest board finished, so one
    board taking 50s delayed every other board's new roles by 50s."""
    slow_started, release = threading.Event(), threading.Event()
    dispatched = []

    def collect(**kw):
        kw["on_board"](main.Collection(matches=["fast role"], outcomes=[("Stripe", "greenhouse", None)]))
        slow_started.set()
        release.wait(5)                # Anduril, still fetching
        kw["on_board"](main.Collection(matches=["slow role"], outcomes=[("Anduril", "greenhouse", None)]))
        return main.Collection(n_enabled=2), main.Collection()

    monkeypatch.setattr(main, "collect_matches", collect)
    monkeypatch.setattr(main, "dispatch",
                        lambda store, c, g, **kw: dispatched.append(list(c.matches)) or len(c.matches))
    boards = watch._Boards(store=None, stats=watch.Stats(), company_interval=120, quick_interval=15)
    boards.full.next_at = float("inf")  # only the quick lane
    boards.tick()
    slow_started.wait(5)
    boards.tick()
    assert dispatched == [["fast role"]]

    release.set()
    boards.quick.future.result()
    boards.tick()
    assert dispatched == [["fast role"], ["slow role"]]   # the sweep's own result adds nothing
    boards.finish()
