"""Core run loop: fetch every enabled source, filter, dedup, notify.

Two entry points share all of this machinery:

* `run()`   — one sweep, then exit. What a cron-style invocation does.
* `watch()` — stay alive and sweep on a timer (see `watch.py`).

Collection is split into two tiers because the sources have wildly different
costs. The aggregator feeds are a single conditional GET each and answer 304
when nothing has changed, so they can be polled every minute. Sweeping every
company's own ATS is hundreds of requests, so it runs on a slower cadence.
"""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field

from . import adapters, filters, log, notify, settings
from .companies import load_companies
from .dedup import KeySet
from .models import CompanyConfig, Job
from .state import SeenStore

logger = log.get()


@dataclass
class Collection:
    matches: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    n_enabled: int = 0
    n_fetched: int = 0
    # False when every aggregator feed answered 304 and companies weren't swept:
    # nothing anywhere has moved, so a caller can skip the rest of the cycle.
    changed: bool = True


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
    # Listings from feeds that curate to software roles upstream are already
    # role-matched by the source, so we only geo-filter them. Everything else
    # gets the full title-based role match.
    if job.source not in settings.PRE_CATEGORIZED_SOURCES and not filters.matches(
        job, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY
    ):
        return False
    if settings.US_CANADA_ONLY and not filters.in_north_america(
        job.location, settings.INCLUDE_UNKNOWN_LOCATIONS
    ):
        return False
    return True


def collect_matches(include_companies: bool = True) -> tuple[Collection, Collection]:
    """Fetch enabled sources, then filter + dedup in one place.

    Returns (curated, general): curated is the companies.md-scoped feed; general
    is every SWE role the aggregators list regardless of company (empty unless
    SIMPLIFY_ALL_ENABLED and a place to send it are both configured).

    With include_companies=False only the cheap aggregator feeds are swept —
    the fast tier of the watch loop.
    """
    result = Collection()
    general = Collection()
    # One KeySet across both tiers and both feeds, so a posting reached through
    # a company's own ATS *and* an aggregator is collected exactly once. Direct
    # adapters are swept first, so the company's own link wins over a mirror.
    seen = KeySet(use_fingerprint=settings.FINGERPRINT_DEDUP)

    if include_companies:
        enabled = [c for c in load_companies(settings.COMPANIES_FILE) if c.enabled]
        result.n_enabled = len(enabled)
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
                    if job in seen or not _passes_filters(job):
                        continue
                    seen.add(job)
                    result.matches.append(job)
                    hits += 1
                if hits:
                    logger.debug("%-18s %4d fetched -> %d match", company.name, len(jobs), hits)

    agg_changed = _collect_aggregators(result, general, seen,
                                       skip_if_unchanged=not include_companies)
    # A sweep that touched company boards always counts as "changed" — those
    # have no conditional-request support, so we genuinely don't know.
    result.changed = include_companies or agg_changed
    return result, general


def _collect_aggregators(result: Collection, general: Collection, seen: KeySet,
                         skip_if_unchanged: bool = False) -> bool:
    """Add matches from the community listings.json feeds (which cover disabled
    companies too), split into the curated (companies.md) feed and the
    unfiltered "all companies" feed. Both come from one fetch.

    `seen` already carries every job matched above, so a posting also present in
    `general` (e.g. a curated company an aggregator also lists broadly) is
    skipped there — no double-alert across the two channels. Returns whether any
    feed reported new content.
    """
    if not settings.SIMPLIFY_ENABLED:
        return False
    from .sources import aggregators
    try:
        curated, all_jobs, changed = aggregators.fetch_pair()
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"Aggregators: {type(exc).__name__}: {exc}")
        return False

    if skip_if_unchanged and not changed:
        # Every feed answered 304, and this sweep isn't touching company boards.
        # The listings are byte-identical to the ones we already filtered, so
        # there is provably nothing new — returning them would just make the
        # caller re-filter and re-check several thousand jobs it has already
        # rejected, once a minute, forever.
        logger.debug("Aggregators: unchanged (304) — skipping this cycle")
        return False

    result.n_fetched += len(curated)
    hits = 0
    for job in curated:
        if job in seen or not _passes_filters(job):
            continue
        seen.add(job)
        result.matches.append(job)
        hits += 1
    logger.info("Aggregators: %d listings from tracked companies -> %d match", len(curated), hits)

    # Only actually run the broad feed once there's somewhere to send it (or
    # we're dry-running to preview it) — otherwise we'd mark jobs "seen" without
    # ever having notified on them, permanently losing them once the webhook is
    # finally wired up.
    if not settings.SIMPLIFY_ALL_ENABLED or not (settings.DISCORD_WEBHOOK_URL_ALL or settings.DRY_RUN):
        return changed

    general.n_fetched += len(all_jobs)
    hits = 0
    for job in all_jobs:
        if job in seen or not _passes_filters(job):
            continue
        seen.add(job)
        general.matches.append(job)
        hits += 1
    logger.info("Aggregators (all companies): %d listings -> %d match", len(all_jobs), hits)
    return changed


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


def select_new(store: SeenStore, matches: list[Job]) -> list[Job]:
    """Jobs from this sweep we have never alerted on, under any dedup key.

    Every match is touched first: that records a still-listed posting as alive
    so pruning can distinguish it from one that was delisted months ago.
    """
    fresh = []
    for job in matches:
        matched_on = store.match(job, use_fingerprint=settings.FINGERPRINT_DEDUP)
        if matched_on is None:
            fresh.append(job)
            continue
        if matched_on == "uid":
            store.touch(job.uid)
        else:
            logger.debug("suppressed duplicate (%s): %s — %s", matched_on, job.company, job.title)
    return fresh


def _seed_quietly(store: SeenStore, new_jobs: list[Job], new_general: list[Job],
                  first_run: bool) -> None:
    """Absorb a backlog into the store without pinging for each role."""
    if first_run:
        for job in new_jobs:
            store.add(job)
    for job in new_general:
        store.add(job)
    store.mark_simplify_all_seeded()


def _absorb_new_sources(store: SeenStore, *buckets: list[Job]) -> dict[str, int]:
    """Quietly absorb the backlog of any source we have not alerted from before.

    Turning on a new feed surfaces its entire back catalogue at once. Those
    roles are new *to us*, not newly posted, and dumping hundreds of them into
    Discord would be indistinguishable from the scraper malfunctioning. So the
    first time a source appears we record its current listings as seen without
    notifying; from the next sweep on, anything it adds is genuinely new.

    Mutates the buckets in place, removing what it absorbed, and returns
    {source: count} for what was absorbed.
    """
    if not settings.SEED_QUIETLY:
        return {}
    present = {job.source for bucket in buckets for job in bucket}
    unseeded = {src for src in present if not store.is_source_seeded(src)}
    if not unseeded:
        return {}

    absorbed: dict[str, int] = {}
    for bucket in buckets:
        keep = []
        for job in bucket:
            if job.source in unseeded:
                store.add(job)
                absorbed[job.source] = absorbed.get(job.source, 0) + 1
            else:
                keep.append(job)
        bucket[:] = keep
    for src in unseeded:
        store.mark_source_seeded(src)
    return absorbed


def dispatch(store: SeenStore, c: Collection, general: Collection) -> int:
    """Notify on everything new in this sweep and record it. Returns how many
    notifications were sent.

    State is saved immediately after each Discord batch rather than at the end:
    a run that dies between sending and saving would otherwise re-send all of it
    next time, which is the single most likely way to spam the channel.
    """
    new_jobs = select_new(store, c.matches)
    new_general = select_new(store, general.matches)

    logger.info(
        "%d match / %d new | %d fetched | %d errors | all-companies: %d match / %d new",
        len(c.matches), len(new_jobs), c.n_fetched, len(c.errors),
        len(general.matches), len(new_general),
    )
    for line in c.errors:
        logger.debug("  ! %s", line)
    _maybe_health_alert(c)

    if not store.existed and settings.SEED_QUIETLY:
        # Genuine first run: absorb the whole backlog silently so we don't dump it.
        _seed_quietly(store, new_jobs, new_general, first_run=True)
        for src in {j.source for j in new_jobs} | {j.source for j in new_general}:
            store.mark_source_seeded(src)
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
        # The store now exists as far as later sweeps in this process are
        # concerned; without this a watch loop would re-seed every cycle.
        store.existed = True
        return 0

    if not store.simplify_all_seeded and settings.SEED_QUIETLY:
        # The main store already existed (not a fresh install) but the
        # all-companies feed was just turned on — seed its backlog quietly too,
        # rather than dumping potentially hundreds of roles in one run.
        _seed_quietly(store, new_jobs, new_general, first_run=False)
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

    if (absorbed := _absorb_new_sources(store, new_jobs, new_general)):
        detail = ", ".join(f"{src or 'direct'}: {n}" for src, n in sorted(absorbed.items()))
        logger.info("New source(s) seeded quietly (%s) — alerting on what they add from now on.",
                    detail)
        if not settings.DRY_RUN:
            store.save()
            notify.notify_summary(
                f"🆕 Added job source(s) — {detail} currently-open role(s) absorbed "
                f"quietly. You'll get pinged when they list something new."
            )

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

    sent = 0
    if to_send:
        notify.notify_jobs(to_send)
        # Record ONLY what we actually sent, so any capped overflow is picked up
        # on the next sweep instead of being silently marked seen and lost.
        for job in to_send:
            store.add(job)
        store.save()
        logger.info("Sent %d notification(s).", len(to_send))
        sent += len(to_send)

    if to_send_general:
        notify.notify_jobs(to_send_general, webhook_url=settings.DISCORD_WEBHOOK_URL_ALL)
        for job in to_send_general:
            store.add(job)
        store.save()
        logger.info("Sent %d all-companies notification(s).", len(to_send_general))
        sent += len(to_send_general)

    return sent


def run() -> int:
    if not settings.DISCORD_WEBHOOK_URL and not settings.DRY_RUN:
        logger.error("DISCORD_WEBHOOK_URL is not set (or use DRY_RUN=true to test).")
        return 2

    store = SeenStore(settings.STATE_FILE)
    c, general = collect_matches()
    dispatch(store, c, general)

    if (dropped := store.prune(settings.PRUNE_DELISTED_DAYS)):
        logger.info("Pruned %d record(s) for postings delisted >%dd ago.",
                    dropped, settings.PRUNE_DELISTED_DAYS)
    if not settings.DRY_RUN:
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
