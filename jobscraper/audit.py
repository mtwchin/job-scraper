"""Verify alerts are genuinely fresh postings, not old jobs newly surfaced.

    python -m jobscraper audit

For every job we alerted on, this computes the **catch latency**: how long after
the board posted it we first saw it. Small numbers mean we're catching things as
they drop; large ones mean we alerted on something that had been sitting there.

Two things are deliberately excluded, because including them answers a different
question and makes a healthy scraper look broken:

* **Quietly-seeded records.** A first run, or a newly added source, absorbs a
  back catalogue without alerting. Those postings are old by construction — they
  were already open when we started watching. They were never alerts, so they
  are not evidence about alert freshness.
* **Records with no usable posting time.** Some boards expose none, and a few
  report the requisition-creation date rather than go-live, so a posting that
  appeared minutes ago can carry a months-old date. Those are counted and
  reported separately rather than silently averaged in.
"""
from __future__ import annotations

import json
from collections import defaultdict
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
    if minutes < 1:
        return f"{int(minutes * 60)}s"
    if minutes < 60:
        return f"{int(minutes)}m"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f}h"
    return f"{minutes / 1440:.1f}d"


def _parse_first_seen(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[idx]


def main() -> int:
    jobs = _load()
    if not jobs:
        print("No state yet — run the scraper first.")
        return 0

    alerted = [j for j in jobs.values() if not j.get("seeded")]
    seeded = len(jobs) - len(alerted)

    rows = []
    undated = 0
    for j in alerted:
        first_seen = _parse_first_seen(j.get("first_seen", ""))
        parsed = parse_posted(j.get("posted_at", "") or "")
        if first_seen is None or parsed is None:
            undated += 1
            continue
        posted_dt, exact = parsed
        latency = max((first_seen - posted_dt).total_seconds() / 60, 0)
        rows.append({
            "first_seen": j.get("first_seen", ""),
            "company": j.get("company", ""),
            "title": j.get("title", ""),
            "source": j.get("source", "") or "direct",
            "latency": latency,
            "exact": exact,
        })

    # Records written before the store learned to distinguish an alert from a
    # quietly-absorbed backlog entry, and to record which source a job came from.
    # Without those fields the numbers below mix seeding into the latency, which
    # reads as terrible freshness — so say so rather than letting the reader draw
    # the wrong conclusion from their own history.
    legacy = sum(1 for j in jobs.values() if "source" not in j)

    print(f"State: {len(jobs)} records — {len(alerted)} alerted on, "
          f"{seeded} absorbed quietly (backlog, not alerts).")
    if legacy:
        print(f"\n  ⚠️  {legacy} record(s) predate this audit's bookkeeping: they carry no")
        print("      source and no seeded/alerted distinction, so first-run and new-source")
        print("      backlog is counted as if it were an alert. Those postings were")
        print("      already open when we started watching, so their 'latency' is really")
        print("      just their age. Treat the figures below as a floor until the store")
        print("      has turned over; alerts recorded from now on are classified properly.")
    if not rows:
        print(f"\nNothing auditable yet: {undated} alert(s) carry no usable posting time.")
        print("Re-run this once a few new alerts have come in.")
        return 0

    rows.sort(key=lambda r: r["first_seen"], reverse=True)
    print(f"{len(rows)} of those carry a posting time and are audited below "
          f"({undated} had none).\n")

    print("Most recent alerts — 'caught after' = time between posting and our alert:")
    print(f"  {'caught after':>12}   {'source':<10} {'company':<16} title")
    for r in rows[:25]:
        flag = "  ⚠️ STALE" if r["latency"] > 24 * 60 else ""
        print(f"  {_fmt(r['latency']):>12}   {r['source']:<10} {r['company']:<16} "
              f"{r['title'][:42]}{flag}")

    lats = sorted(r["latency"] for r in rows)
    n = len(lats)
    within = lambda m: sum(1 for x in lats if x <= m)  # noqa: E731
    print(f"\nFreshness of {n} audited alerts:")
    for label, minutes in (("5 minutes", 5), ("15 minutes", 15),
                           ("1 hour", 60), ("24 hours", 24 * 60)):
        hits = within(minutes)
        print(f"  caught within {label:<11}: {hits}/{n} ({100 * hits // n}%)")
    print(f"  median  : {_fmt(_percentile(lats, 0.5))}")
    print(f"  p90     : {_fmt(_percentile(lats, 0.9))}")

    # Per-source, because the aggregators inherently lag the company's own board:
    # they only list a role once their own tooling has picked it up.
    by_source: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r["latency"])
    if len(by_source) > 1:
        print("\nBy source (aggregators lag — they list a role only once their")
        print("own tooling has seen it, so a company's own board should be faster):")
        for source, values in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
            values.sort()
            print(f"  {source:<12} n={len(values):<5} median={_fmt(_percentile(values, 0.5)):>7}"
                  f"  p90={_fmt(_percentile(values, 0.9)):>7}")

    stale = sum(1 for x in lats if x > 24 * 60)
    if stale:
        print(f"\n  ⚠️ {stale} alert(s) were >24h after the board's posting date. That is")
        print("     usually a board reporting requisition-creation time rather than")
        print("     go-live, not a genuinely stale alert — check the rows above.")
    else:
        print("\n  ✅ Every alert was for a posting newer than 24h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
