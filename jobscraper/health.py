"""Per-company health: one alert per outage, one note when it clears.

This used to be a single error *rate* per sweep, which broke down once the
watch loop ran two kinds of sweep. A priority sweep of 19 boards with five
Workday boards down is 26% and over the threshold; the full sweep of ~136
boards a minute later is 7% and under it, which counted as "recovered" and
re-armed the alert. The result was the same warning every three minutes for
hours.

So health is now tracked per company, across every sweep that touches it. A
company that has failed on consecutive attempts for long enough is reported
once, grouped by platform, and reported again only after it has recovered (with
a note saying so). What has been reported is persisted in the state file, so a
fresh watch loop picking up mid-outage stays quiet too.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass
class Failure:
    adapter: str
    error: str
    since: float        # wall-clock time of the first failure in this streak
    streak: int = 1     # consecutive failed attempts


@dataclass
class Report:
    down: dict[str, Failure]      # newly reportable outages
    recovered: list[str]          # previously reported companies now fetching


class Tracker:
    def __init__(self):
        self.failing: dict[str, Failure] = {}
        self.adapters: dict[str, str] = {}      # every company seen -> adapter

    def record(self, company: str, adapter: str, error: str | None,
               now: float | None = None) -> None:
        self.adapters[company] = adapter
        if error is None:
            self.failing.pop(company, None)
            return
        if (prev := self.failing.get(company)) is not None:
            prev.streak += 1
            prev.error = error
        else:
            self.failing[company] = Failure(adapter, error, now or time.time())

    def to_dict(self) -> dict:
        """Currently-failing boards, for the state file.

        Only the failing set is persisted, not every board's adapter: it is
        normally empty or a handful of entries, and it is the part that has to
        survive a process boundary.
        """
        return {
            name: {"adapter": f.adapter, "error": f.error,
                   "since": f.since, "streak": f.streak}
            for name, f in self.failing.items()
        }

    def load_dict(self, data: dict | None) -> None:
        """Restore failing boards written by an earlier process.

        Streak and `since` are restored rather than reset, so a board that has
        been down for a day still reads as down for a day after a watch loop
        restarts — and a restart no longer silently re-arms the alert delay.
        """
        for name, raw in (data or {}).items():
            if not isinstance(raw, dict):
                continue
            try:
                self.failing[name] = Failure(
                    adapter=str(raw.get("adapter", "")),
                    error=str(raw.get("error", "")),
                    since=float(raw.get("since", 0.0)),
                    streak=int(raw.get("streak", 1)),
                )
            except (TypeError, ValueError):
                continue   # a malformed row must not sink the whole restore
            self.adapters.setdefault(name, str(raw.get("adapter", "")))

    def evaluate(self, reported: set[str], min_streak: int, min_age: float,
                 now: float | None = None) -> Report:
        """What to tell the channel, given who has already been reported."""
        now = now or time.time()
        down = {
            name: f for name, f in self.failing.items()
            if name not in reported and f.streak >= min_streak and now - f.since >= min_age
        }
        # Only companies we've actually seen succeed since count as recovered;
        # one that was skipped (backed off) or not swept yet is still unknown.
        recovered = sorted(name for name in reported
                           if name in self.adapters and name not in self.failing)
        return Report(down, recovered)


_URL = re.compile(r"\s*for url: \S+")


def short_error(error: str) -> str:
    """Strip the bulky parts (adapter tag, request URL) from an error line."""
    error = _URL.sub("", error)
    return re.sub(r"^\[[^\]]+\]\s*", "", error).strip()


def format_down(report: Report, tracker: Tracker, now: float | None = None) -> str:
    now = now or time.time()
    by_adapter: dict[str, list[str]] = {}
    for name, f in sorted(report.down.items()):
        by_adapter.setdefault(f.adapter, []).append(name)
    oldest = max(now - f.since for f in report.down.values())
    lines = [f"⚠️ Scraper health: {len(report.down)} compan{'y' if len(report.down) == 1 else 'ies'} "
             f"failing for {_fmt_age(oldest)}."]
    for adapter, names in sorted(by_adapter.items(), key=lambda kv: -len(kv[1])):
        tracked = sum(1 for a in tracker.adapters.values() if a == adapter)
        scope = f"{len(names)}/{tracked}" if tracked else str(len(names))
        sample = short_error(report.down[names[0]].error)
        lines.append(f"• **{adapter}** ({scope}): {', '.join(names)} — {sample}")
    lines.append("They're backed off and retried automatically; you'll get a ✅ when they recover.")
    return "\n".join(lines)


def format_recovered(names: list[str]) -> str:
    return f"✅ Scraper health: fetching again — {', '.join(names)}."


def _fmt_age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"{minutes} min"
    return f"{minutes / 60:.1f} h"
