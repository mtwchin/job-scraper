"""Long-lived polling loop — the thing that actually makes alerts fast.

Why this exists: the workflow asks for `*/5 * * * *`, but GitHub throttles
scheduled workflows on a busy fleet and delivers them far less often. Measured
on this repo, consecutive scheduled runs landed 2-6 hours apart, and the fastest
posting we ever caught was ten minutes old. No amount of scraper tuning fixes a
scheduler that doesn't fire; the process has to stay alive and poll on its own
clock.

So one invocation stays up for hours and sweeps on a timer:

* Every WATCH_INTERVAL (default 60s) it polls the aggregator feeds. Those are
  conditional GETs that answer 304 when nothing has changed, so an idle cycle
  costs a couple of hundred milliseconds and no parsing at all.
* Every WATCH_COMPANY_INTERVAL (default 300s) it also sweeps every company's own
  ATS, which is hundreds of requests and can't be short-circuited.

State lives in memory for the life of the loop and is flushed to disk on a timer
and immediately after anything is sent, so a killed runner loses at most one
flush interval — and never re-sends what it already delivered.
"""
from __future__ import annotations

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


def _sleep_until(deadline: float, stopper: _Stopper) -> None:
    """Sleep toward `deadline`, waking often enough to notice a stop signal."""
    while not stopper.stop:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))


def watch() -> int:
    if not settings.DISCORD_WEBHOOK_URL and not settings.DRY_RUN:
        logger.error("DISCORD_WEBHOOK_URL is not set (or use DRY_RUN=true to test).")
        return 2

    interval = max(settings.WATCH_INTERVAL, 15)
    company_interval = max(settings.WATCH_COMPANY_INTERVAL, interval)
    duration = settings.WATCH_DURATION
    stopper = _Stopper()
    store = SeenStore(settings.STATE_FILE)
    stats = Stats()

    logger.info(
        "watch: polling feeds every %ds, full company sweep every %ds, for up to %s "
        "(%d records already known)",
        interval, company_interval, _fmt_duration(duration), len(store),
    )

    end_at = time.monotonic() + duration
    next_company_sweep = 0.0   # sweep companies on the very first cycle
    next_flush = time.monotonic() + settings.WATCH_FLUSH_INTERVAL
    next_heartbeat = time.monotonic() + _HEARTBEAT_INTERVAL

    while not stopper.stop and time.monotonic() < end_at:
        cycle_started = time.monotonic()
        include_companies = cycle_started >= next_company_sweep
        stats.cycles += 1

        try:
            c, general = main.collect_matches(include_companies=include_companies)
            if include_companies:
                stats.company_sweeps += 1
                next_company_sweep = cycle_started + company_interval

            if not c.changed:
                # Every feed answered 304 and we didn't sweep companies, so
                # collect_matches returned nothing to consider. Skip dispatch
                # entirely rather than re-deciding several thousand already-seen
                # jobs once a minute.
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
            logger.debug("watch: cycle %d took %.1fs, longer than the %ds interval",
                         stats.cycles, elapsed, interval)
        if now >= next_heartbeat:
            logger.info("watch: %s in — %d cycles (%d idle), %d sent, %d records",
                        _fmt_duration(int(stats.uptime())), stats.cycles,
                        stats.idle_cycles, stats.sent, len(store))
            next_heartbeat = now + _HEARTBEAT_INTERVAL
        # Never sleep past the deadline: overshooting by a whole interval would
        # push a long run past the job limit it was sized to fit inside.
        _sleep_until(min(cycle_started + interval, end_at), stopper)

    # Prune before the final save so the committed state file stays bounded.
    if (dropped := store.prune(settings.PRUNE_DELISTED_DAYS)):
        logger.info("Pruned %d record(s) for postings delisted >%dd ago.",
                    dropped, settings.PRUNE_DELISTED_DAYS)
    if not settings.DRY_RUN:
        store.save()

    logger.info(
        "watch: done after %s — %d cycles (%d idle, %d full sweeps), %d notification(s), "
        "%d error(s), %d records",
        _fmt_duration(int(stats.uptime())), stats.cycles, stats.idle_cycles,
        stats.company_sweeps, stats.sent, stats.errors, len(store),
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
