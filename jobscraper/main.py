"""Entry point: fetch every enabled company, filter, dedup, notify."""
from __future__ import annotations

import sys
import traceback

from . import adapters, filters, notify, settings
from .companies import load_companies
from .models import Job
from .state import SeenStore


def collect_matches() -> tuple[list[Job], list[str]]:
    """Return (matching jobs across all companies, human-readable error lines)."""
    companies = load_companies(settings.COMPANIES_FILE)
    matches: list[Job] = []
    errors: list[str] = []
    seen_uids: set[str] = set()

    enabled = [c for c in companies if c.enabled]
    print(f"Checking {len(enabled)} enabled companies "
          f"(roles={sorted(settings.ROLE_TYPES)}, off_season_only={settings.OFF_SEASON_ONLY}, "
          f"us_canada_only={settings.US_CANADA_ONLY}, max_age_days={settings.MAX_AGE_DAYS})")

    for company in enabled:
        fetch = adapters.get(company.adapter)
        if fetch is None:
            errors.append(f"{company.name}: unknown adapter '{company.adapter}'")
            continue
        try:
            jobs = fetch(company)
        except Exception as exc:  # one company must never kill the run
            errors.append(f"{company.name} [{company.adapter}]: {type(exc).__name__}: {exc}")
            continue

        hits = 0
        for job in jobs:
            if not job.url or job.uid in seen_uids:
                continue
            if not filters.matches(job, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY):
                continue
            if settings.US_CANADA_ONLY and not filters.in_north_america(
                job.location, settings.INCLUDE_UNKNOWN_LOCATIONS
            ):
                continue
            if settings.MAX_AGE_DAYS > 0:
                age = filters.posted_age_days(job.posted_at)
                if age is not None and age > settings.MAX_AGE_DAYS:
                    continue
            seen_uids.add(job.uid)
            matches.append(job)
            hits += 1
        print(f"  {company.name:<16} {len(jobs):>4} fetched  ->  {hits} match")

    return matches, errors


def run() -> int:
    if not settings.DISCORD_WEBHOOK_URL and not settings.DRY_RUN:
        print("ERROR: DISCORD_WEBHOOK_URL is not set. "
              "Set it in the environment (or use DRY_RUN=true to test).", file=sys.stderr)
        return 2

    store = SeenStore(settings.STATE_FILE)
    matches, errors = collect_matches()

    new_jobs = [j for j in matches if store.is_new(j.uid)]
    print(f"\n{len(matches)} matching role(s) total, {len(new_jobs)} new since last run.")

    if errors:
        print(f"\n{len(errors)} company error(s):")
        for line in errors:
            print(f"  ! {line}")

    first_run = not store.existed
    for job in new_jobs:
        store.add(job.uid, job.title, job.company, job.url)

    if first_run and settings.SEED_QUIETLY:
        # Don't blast hundreds of already-open roles on the first run.
        print("First run: seeding state quietly (no per-job pings).")
        if not settings.DRY_RUN:
            notify.notify_summary(
                f"✅ Internship Radar is live. Tracking is on — seeded "
                f"{len(new_jobs)} currently-open matching role(s). "
                f"You'll get pinged when *new* ones drop."
            )
            store.save()
        return 0

    to_send = new_jobs[: settings.MAX_NOTIFICATIONS_PER_RUN]
    if len(new_jobs) > len(to_send):
        print(f"Capping notifications at {settings.MAX_NOTIFICATIONS_PER_RUN} "
              f"(had {len(new_jobs)}).")

    if settings.DRY_RUN:
        print("\n[DRY_RUN] Would notify about:")
        for j in to_send:
            print(f"  - {j.company}: {j.title}  {j.url}")
        return 0

    if to_send:
        notify.notify_jobs(to_send)
    if new_jobs:  # only rewrite state when something actually changed
        store.save()
    print("Done.")
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
