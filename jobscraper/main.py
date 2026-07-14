"""Core run loop: fetch every enabled company (concurrently), filter, dedup, notify."""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field

from . import adapters, filters, log, notify, settings
from .companies import load_companies
from .models import CompanyConfig, Job
from .state import SeenStore

logger = log.get()


@dataclass
class Collection:
    matches: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    n_enabled: int = 0
    n_fetched: int = 0


def _fetch_company(company: CompanyConfig) -> tuple[CompanyConfig, list[Job], str | None]:
    """Fetch one company. Never raises — returns an error string instead so a
    single bad board can't take down the run."""
    fetch = adapters.get(company.adapter)
    if fetch is None:
        return company, [], f"unknown adapter '{company.adapter}'"
    try:
        return company, fetch(company), None
    except Exception as exc:  # noqa: BLE001 - isolation is the whole point
        return company, [], f"[{company.adapter}] {type(exc).__name__}: {exc}"


def _passes_filters(job: Job) -> bool:
    """Role + location only. We deliberately do NOT gate on the board's posted
    date: many boards (e.g. Lever) report the requisition-creation date, not when
    a role goes live, so a freshly-listed job can carry a months-old date. Gating
    on that permanently hides real new postings. "Newly dropped" is instead
    determined by dedup (first time we see it) + quiet first-run seeding."""
    if not job.url:
        return False
    # Simplify listings are already curated to software intern/new-grad by the
    # source (via Simplify's category), so we only geo-filter them here. Direct
    # adapter jobs get the full title-based role match.
    if job.source != "simplify" and not filters.matches(
        job, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY
    ):
        return False
    if settings.US_CANADA_ONLY and not filters.in_north_america(
        job.location, settings.INCLUDE_UNKNOWN_LOCATIONS
    ):
        return False
    return True


def collect_matches() -> tuple[Collection, Collection]:
    """Fetch all enabled companies in parallel, then filter + dedup in one place.
    Returns (curated, general): curated is the existing companies.md-scoped feed;
    general is every SWE role Simplify lists regardless of company (empty unless
    SIMPLIFY_ALL_ENABLED and a place to send it are both configured)."""
    enabled = [c for c in load_companies(settings.COMPANIES_FILE) if c.enabled]
    result = Collection(n_enabled=len(enabled))
    general = Collection()
    seen_uids: set[str] = set()

    logger.info(
        "Checking %d companies | roles=%s off_season=%s us_ca=%s concurrency=%d (freshness=dedup)",
        len(enabled), sorted(settings.ROLE_TYPES), settings.OFF_SEASON_ONLY,
        settings.US_CANADA_ONLY, settings.CONCURRENCY,
    )

    with cf.ThreadPoolExecutor(max_workers=settings.CONCURRENCY) as ex:
        for company, jobs, error in ex.map(_fetch_company, enabled):
            if error is not None:
                result.errors.append(f"{company.name}: {error}")
                logger.debug("%-18s ERROR %s", company.name, error)
                continue
            result.n_fetched += len(jobs)
            hits = 0
            for job in jobs:
                if job.uid in seen_uids or not _passes_filters(job):
                    continue
                seen_uids.add(job.uid)
                result.matches.append(job)
                hits += 1
            if hits:
                logger.debug("%-18s %4d fetched -> %d match", company.name, len(jobs), hits)

    _collect_simplify(result, general, seen_uids)
    return result, general


def _collect_simplify(result: Collection, general: Collection, seen_uids: set[str]) -> None:
    """Add matches from the SimplifyJobs aggregator (covers disabled companies too),
    split into the curated (companies.md) feed and the unfiltered "all companies"
    feed. Both come from one fetch. `seen_uids` already carries every uid matched
    above, so a job also present in `general` (e.g. a curated company Simplify also
    lists broadly) is skipped there — no double-alert across the two channels."""
    if not settings.SIMPLIFY_ENABLED:
        return
    from .sources import simplify
    try:
        curated, all_jobs = simplify.fetch_pair()
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"Simplify: {type(exc).__name__}: {exc}")
        return

    result.n_fetched += len(curated)
    hits = 0
    for job in curated:
        if job.uid in seen_uids or not _passes_filters(job):
            continue
        seen_uids.add(job.uid)
        result.matches.append(job)
        hits += 1
    logger.info("Simplify: %d listings from tracked companies -> %d match", len(curated), hits)

    # Only actually run the broad feed once there's somewhere to send it (or
    # we're dry-running to preview it) — otherwise we'd mark jobs "seen" without
    # ever having notified on them, permanently losing them once the webhook is
    # finally wired up.
    if not settings.SIMPLIFY_ALL_ENABLED or not (settings.DISCORD_WEBHOOK_URL_ALL or settings.DRY_RUN):
        return

    general.n_fetched += len(all_jobs)
    hits = 0
    for job in all_jobs:
        if job.uid in seen_uids or not _passes_filters(job):
            continue
        seen_uids.add(job.uid)
        general.matches.append(job)
        hits += 1
    logger.info("Simplify (all companies): %d listings -> %d match", len(all_jobs), hits)


def _maybe_health_alert(c: Collection) -> None:
    """Warn on Discord if an unusually large share of companies failed this run."""
    if c.n_enabled == 0:
        return
    rate = len(c.errors) / c.n_enabled
    if rate >= settings.HEALTH_ALERT_THRESHOLD:
        msg = (
            f"⚠️ Scraper health: {len(c.errors)}/{c.n_enabled} companies errored "
            f"this run ({rate:.0%}). Possible platform outage or a broken adapter. "
            f"First few: " + "; ".join(c.errors[:3])
        )
        logger.warning(msg)
        if not settings.DRY_RUN and settings.DISCORD_WEBHOOK_URL:
            notify.notify_summary(msg)


def run() -> int:
    if not settings.DISCORD_WEBHOOK_URL and not settings.DRY_RUN:
        logger.error("DISCORD_WEBHOOK_URL is not set (or use DRY_RUN=true to test).")
        return 2

    store = SeenStore(settings.STATE_FILE)
    c, general = collect_matches()
    new_jobs = [j for j in c.matches if store.is_new(j.uid)]
    new_general = [j for j in general.matches if store.is_new(j.uid)]

    logger.info(
        "%d match / %d new | %d fetched | %d errors | all-companies: %d match / %d new",
        len(c.matches), len(new_jobs), c.n_fetched, len(c.errors),
        len(general.matches), len(new_general),
    )
    if c.errors:
        for line in c.errors:
            logger.debug("  ! %s", line)
    _maybe_health_alert(c)

    if not store.existed and settings.SEED_QUIETLY:
        # Genuine first run: absorb the whole backlog silently so we don't dump it.
        for job in new_jobs:
            store.add(job.uid, job.title, job.company, job.url, job.posted_at)
        for job in new_general:
            store.add(job.uid, job.title, job.company, job.url, job.posted_at)
        store.mark_simplify_all_seeded()
        logger.info("First run: seeding %d + %d (all-companies) roles quietly (no per-job pings).",
                    len(new_jobs), len(new_general))
        if not settings.DRY_RUN:
            notify.notify_summary(
                f"✅ Internship Radar is live — seeded {len(new_jobs)} currently-open "
                f"role(s). You'll get pinged when new ones drop."
            )
            if new_general and settings.DISCORD_WEBHOOK_URL_ALL:
                notify.notify_summary(
                    f"✅ All-companies feed is live — seeded {len(new_general)} currently-open "
                    f"role(s). You'll get pinged when new ones drop.",
                    webhook_url=settings.DISCORD_WEBHOOK_URL_ALL,
                )
            store.save()
        return 0

    if not store.simplify_all_seeded and settings.SEED_QUIETLY:
        # The main store already existed (not a fresh install) but the
        # all-companies feed was just turned on — seed its backlog quietly too,
        # rather than dumping potentially hundreds of roles in one run. Gated on
        # SEED_QUIETLY so explicitly disabling quiet-seeding applies to this feed
        # too, not just the main one.
        for job in new_general:
            store.add(job.uid, job.title, job.company, job.url, job.posted_at)
        store.mark_simplify_all_seeded()
        logger.info("All-companies feed: first run, seeding %d roles quietly.", len(new_general))
        if not settings.DRY_RUN:
            if new_general and settings.DISCORD_WEBHOOK_URL_ALL:
                notify.notify_summary(
                    f"✅ All-companies feed is live — seeded {len(new_general)} currently-open "
                    f"role(s). You'll get pinged when new ones drop.",
                    webhook_url=settings.DISCORD_WEBHOOK_URL_ALL,
                )
            store.save()
        new_general = []

    to_send = new_jobs[: settings.MAX_NOTIFICATIONS_PER_RUN]
    if len(new_jobs) > len(to_send):
        logger.warning("Capping at %d this run; the other %d will send next run(s).",
                       settings.MAX_NOTIFICATIONS_PER_RUN, len(new_jobs) - len(to_send))

    to_send_general = new_general[: settings.MAX_NOTIFICATIONS_PER_RUN]
    if len(new_general) > len(to_send_general):
        logger.warning("All-companies feed: capping at %d this run; the other %d will send "
                       "next run(s).", settings.MAX_NOTIFICATIONS_PER_RUN,
                       len(new_general) - len(to_send_general))

    if settings.DRY_RUN:
        for j in to_send:
            logger.info("[DRY_RUN] would notify: %s — %s  %s", j.company, j.title, j.url)
        for j in to_send_general:
            logger.info("[DRY_RUN] would notify (all-companies): %s — %s  %s",
                        j.company, j.title, j.url)
        return 0

    sent_any = False
    if to_send:
        notify.notify_jobs(to_send)
        # Seed ONLY what we actually sent, so any capped overflow is picked up on
        # the next run instead of being silently marked seen and lost.
        for job in to_send:
            store.add(job.uid, job.title, job.company, job.url, job.posted_at)
        logger.info("Sent %d notification(s).", len(to_send))
        sent_any = True

    if to_send_general:
        notify.notify_jobs(to_send_general, webhook_url=settings.DISCORD_WEBHOOK_URL_ALL)
        for job in to_send_general:
            store.add(job.uid, job.title, job.company, job.url, job.posted_at)
        logger.info("Sent %d all-companies notification(s).", len(to_send_general))
        sent_any = True

    if sent_any:
        store.save()
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        logger.exception("Unhandled error during run")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
