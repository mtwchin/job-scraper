"""Verify alerts are genuinely fresh postings, not old jobs newly surfaced.

    python -m jobscraper.audit

For every job we've alerted on, it computes the "catch latency" = how long after
the board posted it we first saw/alerted it. If the scraper is doing its job, that
number is small (minutes/hours). A large latency would mean we alerted an old
posting — exactly what you're checking for.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import settings
from .filters import parse_posted


def _load() -> dict:
    if not settings.STATE_FILE.exists():
        return {}
    try:
        return json.loads(settings.STATE_FILE.read_text(encoding="utf-8")).get("jobs", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _fmt(minutes: float) -> str:
    if minutes < 60:
        return f"{int(minutes)}m"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f}h"
    return f"{minutes / 1440:.1f}d"


def main() -> int:
    jobs = _load()
    if not jobs:
        print("No state yet — run the scraper first.")
        return 0

    rows = []
    for j in jobs.values():
        first_seen = j.get("first_seen")
        posted = j.get("posted_at", "")
        fs = None
        if first_seen:
            try:
                fs = datetime.fromisoformat(first_seen)
                if fs.tzinfo is None:
                    fs = fs.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        parsed = parse_posted(posted) if posted else None
        latency = None
        if fs and parsed:
            posted_dt, _ = parsed
            latency = max((fs - posted_dt).total_seconds() / 60, 0)
        rows.append((first_seen or "", j.get("company", ""), j.get("title", ""), latency))

    rows.sort(reverse=True)  # most recent alerts first
    tracked = [r for r in rows if r[3] is not None]

    print(f"State: {len(jobs)} jobs recorded, {len(tracked)} with a posting time to audit.\n")
    if not tracked:
        print("No auditable entries yet. Posting times are recorded from now on —")
        print("re-run this after a few new alerts come in.")
        return 0

    print("Most recent alerts — 'caught after' = time between posting and our alert:")
    print(f"  {'caught after':>12}   {'company':<16} title")
    for first_seen, co, title, lat in rows[:25]:
        if lat is None:
            continue
        flag = "  ⚠️ STALE" if lat > 24 * 60 else ""
        print(f"  {_fmt(lat):>12}   {co:<16} {title[:46]}{flag}")

    lats = [r[3] for r in tracked]
    within_1h = sum(1 for l in lats if l <= 60)
    within_24h = sum(1 for l in lats if l <= 24 * 60)
    n = len(lats)
    print(f"\nFreshness of {n} audited alerts:")
    print(f"  caught within 1 hour of posting : {within_1h}/{n} ({100*within_1h//n}%)")
    print(f"  caught within 24 hours          : {within_24h}/{n} ({100*within_24h//n}%)")
    print(f"  median catch latency            : {_fmt(sorted(lats)[n // 2])}")
    if within_24h < n:
        print("  ⚠️ Some alerts were >24h after posting — investigate those rows above.")
    else:
        print("  ✅ Every alert was for a posting newer than 24h. Working as intended.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
