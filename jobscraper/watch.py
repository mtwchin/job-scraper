"""Long-lived polling loop — the thing that actually makes alerts fast.

Why this exists: the workflow asks for `*/5 * * * *`, but GitHub throttles
scheduled workflows on a busy fleet and delivers them far less often. Measured
on this repo, consecutive scheduled runs landed 2-6 hours apart, and the fastest
posting we ever caught was ten minutes old. No amount of scraper tuning fixes a
scheduler that doesn't fire; the process has to stay alive and poll on its own
clock.

So one invocation stays up for hours and sweeps on a timer:

* Every WATCH_INTERVAL (default 20s) it polls the aggregator feeds. Those are
  conditional requests that answer 304 when nothing has changed, so an idle
  cycle costs a couple of hundred milliseconds and no parsing at all.
* On background threads, every WATCH_COMPANY_INTERVAL (default 120s) it sweeps
  every company's own ATS, which is hundreds of requests and can't be
  short-circuited, and every WATCH_QUICK_INTERVAL (60s), in a lane of its own,
  it takes a quick look at every board's newest postings. A sweep in progress
  never delays a feed poll or the other lane.

State lives in memory for the life of the loop and is flushed to disk on a timer
and immediately after anything is sent, so a killed runner loses at most one
flush interval — and never re-sends what it already delivered.
"""
from __future__ import annotations

import concurrent.futures as cf
import queue
import signal
import time
from dataclasses import dataclass, field

from . import log, main, settings
from .state import SeenStore

logger = log.get()

# How often a long run reports that it's alive. Runs for hours, so without this
# the Actions log is silent for most of it and a wedged loop looks identical to
# a quiet one.
_HEARTBEAT_INTERVAL = 30 * 60


@dataclass
class Stats:
    cycles: int = 0
    company_sweeps: int = 0
    quick_sweeps: int = 0
    sent: int = 0
    idle_cycles: int = 0        # nothing changed upstream; cycle short-circuited
    errors: int = 0
    started: float = field(default_factory=time.monotonic)

    def uptime(self) -> float:
        return time.monotonic() - self.started


class _Stopper:
    """Turns SIGINT/SIGTERM into a clean exit.

    A GitHub runner sends SIGTERM when it's tearing a job down. Catching it lets
    the loop finish the cycle it's in and flush state, instead of being killed
    mid-write and losing the record of what we just sent.
    """

    def __init__(self):
        self.stop = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle)
            except ValueError:
                pass  # not on the main thread; the duration bound still applies

    def _handle(self, signum, _frame):
        logger.info("Received signal %s — finishing this cycle and shutting down.", signum)
        self.stop = True


def _sleep_until(deadline: float, stopper: _Stopper, on_wake=None) -> None:
    """Sleep toward `deadline`, waking every second to notice a stop signal and
    to run `on_wake` (which dispatches a finished board sweep without waiting
    for the next feed poll)."""
    while not stopper.stop:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))
        if on_wake is not None:
            try:
                on_wake()
            except Exception:  # noqa: BLE001
                logger.exception("watch: background sweep handling failed; continuing")


class _Lane:
    """One kind of board sweep on its own worker thread."""

    def __init__(self, name: str, interval: int, quick: bool):
        self.name, self.interval, self.quick = name, interval, quick
        self.pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"boards-{name}")
        self.future: cf.Future | None = None
        self.next_at = 0.0          # sweep right away
        # Boards the running sweep has finished, waiting for the main thread.
        self.done: queue.SimpleQueue[main.Collection] = queue.SimpleQueue()

    def drain(self) -> main.Collection | None:
        """Every board finished since the last drain, as one collection."""
        c = None
        while True:
            try:
                board = self.done.get_nowait()
            except queue.Empty:
                return c
            if c is None:
                c = main.Collection()
            c.absorb(board)


class _Boards:
    """Company-board sweeps, run on background threads.

    A full sweep takes 15-90s and used to sit in front of every feed poll, so a
    role that had just landed in a feed waited behind it. Now sweeps run beside
    the feed poller, and each board's results are dispatched on the main thread
    within a second of that board finishing, not when the sweep's slowest
    board does. Dispatch stays single-threaded, so the store needs no locking.

    Quick sweeps get a lane of their own. Sharing one worker with the full
    sweep, they ran about once a minute whatever their interval said, because a
    quick sweep could only start once the full sweep ahead of it had finished.
    A quick sweep reads only each board's newest postings (see
    CompanyConfig.quick), so it takes seconds and can run every few.
    """

    def __init__(self, store: SeenStore, stats: Stats, company_interval: int,
                 quick_interval: int):
        self.store, self.stats = store, stats
        self.full = _Lane("full", company_interval, quick=False)
        self.quick = _Lane("quick", quick_interval, quick=True)

    def tick(self) -> None:
        """Dispatch any finished sweep, then start each lane's next one if due."""
        if settings.SCOPE == "rest":
            return                  # the broad tier never sweeps boards
        for lane in (self.quick, self.full):
            self._tick(lane)

    def _tick(self, lane: _Lane) -> None:
        # Drain before checking the future: a board can land between the two,
        # and the future finishing only after the drain means no board is left.
        boards = lane.drain()
        finished = lane.future is not None and lane.future.done()
        if boards is not None:
            self._dispatch(lane, boards, main.Collection())
        if lane.future is not None:
            if not finished:
                return
            future, lane.future = lane.future, None
            if (boards := lane.drain()) is not None:
                self._dispatch(lane, boards, main.Collection())
            try:
                c, general = future.result()
            except Exception:  # noqa: BLE001 - one bad sweep must not end the loop
                self.stats.errors += 1
                logger.exception("watch: %s sweep failed; continuing", lane.name)
            else:
                # Its boards went out above; what is left is only bookkeeping.
                if c.matches or general.matches or c.outcomes:
                    self._dispatch(lane, c, general)

        now = time.monotonic()
        if now < lane.next_at:
            return
        lane.next_at = now + lane.interval
        if lane.quick:
            self.stats.quick_sweeps += 1
        else:
            self.stats.company_sweeps += 1
        lane.future = lane.pool.submit(main.collect_matches, include_companies=True,
                                       quick=lane.quick,
                                       include_aggregators=False,
                                       on_board=lane.done.put)

    def _dispatch(self, lane: _Lane, c: main.Collection, general: main.Collection) -> None:
        try:
            self.stats.sent += main.dispatch(self.store, c, general, quiet=True)
            self.stats.errors += len(c.errors)
        except Exception:  # noqa: BLE001 - one bad dispatch must not end the loop
            self.stats.errors += 1
            logger.exception("watch: %s sweep dispatch failed; continuing", lane.name)

    def finish(self) -> None:
        """Let in-flight sweeps land so what they found is not dropped."""
        for lane in (self.quick, self.full):
            if lane.future is not None:
                cf.wait([lane.future])
            lane.next_at = float("inf")
            self._tick(lane)
            lane.pool.shutdown(wait=True)


def watch() -> int:
    if not settings.DISCORD_WEBHOOK_URL and not settings.DRY_RUN:
        logger.error("DISCORD_WEBHOOK_URL is not set (or use DRY_RUN=true to test).")
        return 2

    interval = max(settings.WATCH_INTERVAL, 5)
    company_interval = max(settings.WATCH_COMPANY_INTERVAL, 15)
    quick_interval = max(settings.WATCH_QUICK_INTERVAL, 10)
    duration = settings.WATCH_DURATION
    stopper = _Stopper()
    store = SeenStore(settings.STATE_FILE)
    stats = Stats()
    boards = _Boards(store, stats, company_interval, quick_interval)

    boards_desc = ("no board sweeps" if settings.SCOPE == "rest" else
                   f"quick board sweep every {quick_interval}s, "
                   f"full company sweep every {company_interval}s")
    logger.info(
        "watch [scope=%s]: polling feeds every %ds, %s, for up to %s "
        "(%d records already known; feed commit lookup %s)",
        settings.SCOPE, interval, boards_desc, _fmt_duration(duration), len(store),
        "on" if settings.GITHUB_TOKEN else "off, no GITHUB_TOKEN",
    )

    end_at = time.monotonic() + duration
    next_flush = time.monotonic() + settings.WATCH_FLUSH_INTERVAL
    next_heartbeat = time.monotonic() + _HEARTBEAT_INTERVAL

    while not stopper.stop and time.monotonic() < end_at:
        cycle_started = time.monotonic()
        stats.cycles += 1
        boards.tick()

        try:
            c, general = main.collect_matches(include_companies=False)
            if not c.changed:
                # Every feed is unchanged, so there is provably nothing new.
                # Skip dispatch rather than re-deciding several thousand
                # already-seen jobs every poll.
                stats.idle_cycles += 1
            else:
                stats.sent += main.dispatch(store, c, general)
            stats.errors += len(c.errors)
        except Exception:  # noqa: BLE001 - a loop that dies on one bad cycle is useless
            stats.errors += 1
            logger.exception("watch: cycle %d failed; continuing", stats.cycles)

        now = time.monotonic()
        if store.dirty and now >= next_flush:
            store.save()
            next_flush = now + settings.WATCH_FLUSH_INTERVAL

        elapsed = time.monotonic() - cycle_started
        if elapsed > interval:
            logger.debug("watch: feed poll %d took %.1fs, longer than the %ds interval",
                         stats.cycles, elapsed, interval)
        if now >= next_heartbeat:
            logger.info("watch: %s in — %d feed polls (%d idle), %d full / %d quick sweeps, "
                        "%d sent, %d records",
                        _fmt_duration(int(stats.uptime())), stats.cycles, stats.idle_cycles,
                        stats.company_sweeps, stats.quick_sweeps, stats.sent, len(store))
            next_heartbeat = now + _HEARTBEAT_INTERVAL
        # Never sleep past the deadline: overshooting by a whole interval would
        # push a long run past the job limit it was sized to fit inside.
        _sleep_until(min(cycle_started + interval, end_at), stopper, boards.tick)

    boards.finish()
    # Prune before the final save so the committed state file stays bounded.
    if (dropped := store.prune(settings.PRUNE_DELISTED_DAYS)):
        logger.info("Pruned %d record(s) for postings delisted >%dd ago.",
                    dropped, settings.PRUNE_DELISTED_DAYS)
    if not settings.DRY_RUN:
        store.save()

    logger.info(
        "watch: done after %s — %d feed polls (%d idle, %d full sweeps, %d quick sweeps), "
        "%d notification(s), %d error(s), %d records",
        _fmt_duration(int(stats.uptime())), stats.cycles, stats.idle_cycles,
        stats.company_sweeps, stats.quick_sweeps, stats.sent, stats.errors, len(store),
    )
    return 0


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def main_entry() -> int:
    try:
        return watch()
    except Exception:
        logger.exception("Unhandled error in watch loop")
        return 1
