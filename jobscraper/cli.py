"""Unified command-line interface.

    jobscraper run            # one sweep: fetch, filter, notify, exit
    jobscraper watch          # poll continuously (the scheduled command)
    jobscraper list           # show tracked companies + adapter breakdown
    jobscraper audit          # freshness report of past alerts
    jobscraper discover NAME  # detect a company's ATS config
    jobscraper probe ADAPTER CONFIG  # check one adapter+config end to end
    jobscraper test-webhook   # send a test message to your Discord webhook
"""
from __future__ import annotations

import argparse
import collections
import sys

from . import log, settings


def _cmd_run(_args) -> int:
    from .main import main
    return main()


def _cmd_watch(args) -> int:
    from .watch import main_entry
    if args.interval:
        settings.WATCH_INTERVAL = args.interval
    if args.company_interval:
        settings.WATCH_COMPANY_INTERVAL = args.company_interval
    if args.duration:
        settings.WATCH_DURATION = args.duration
    return main_entry()


def _cmd_probe(args) -> int:
    """Run one adapter against one config and show what it actually returns.

    `discover` answers "does this board exist?"; this answers "does our adapter
    parse it correctly?" — which is the part a unit test against a recorded
    payload cannot prove.
    """
    from . import adapters, filters
    from .models import CompanyConfig

    fetch = adapters.get(args.adapter)
    if fetch is None:
        print(f"Unknown adapter '{args.adapter}'. Known: {', '.join(sorted(adapters.REGISTRY))}")
        return 2

    params = dict(
        kv.split("=", 1) for kv in args.config.split(";") if "=" in kv
    ) if args.config else {}
    company = CompanyConfig(name=args.name or args.adapter, adapter=args.adapter, params=params)

    try:
        jobs = fetch(company)
    except Exception as exc:  # noqa: BLE001 - the error IS the result here
        print(f"❌ {args.adapter} {args.config}: {type(exc).__name__}: {exc}")
        return 1

    matching = [
        j for j in jobs
        if filters.matches(j, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY)
        and (not settings.US_CANADA_ONLY
             or filters.in_north_america(j.location, settings.INCLUDE_UNKNOWN_LOCATIONS))
    ]
    print()
    print(f"{'✅' if jobs else '❌'} {args.adapter}  {args.config}")
    print(f"   {len(jobs)} posting(s) fetched, {len(matching)} match the intern/new-grad filter")
    for j in (matching or jobs)[:5]:
        print(f"     - {j.title[:60]:<60} | {j.location[:28]:<28} | {j.url[:60]}")
    if jobs and not all(j.url for j in jobs):
        print("   ⚠️  some postings came back with no URL — check the adapter's url field")
    return 0 if jobs else 1


def _cmd_merge_state(args) -> int:
    """Union another state file into ours — see SeenStore.merge_from."""
    from pathlib import Path

    from .state import SeenStore

    other = Path(args.other)
    if not other.exists():
        print(f"[merge-state] {other} does not exist; nothing to merge.")
        return 0
    store = SeenStore(settings.STATE_FILE)
    before = len(store)
    added = store.merge_from(other)
    store.save()
    print(f"[merge-state] {before} local + {added} new from {other} = {len(store)} records")
    return 0


def _cmd_list(args) -> int:
    from .companies import load_companies
    companies = load_companies(settings.COMPANIES_FILE)
    enabled = [c for c in companies if c.enabled]
    by_adapter = collections.Counter(c.adapter for c in enabled)
    print(f"{len(companies)} companies — {len(enabled)} enabled, "
          f"{len(companies) - len(enabled)} disabled\n")
    print("Enabled by adapter:")
    for adapter, n in by_adapter.most_common():
        print(f"  {adapter:<12} {n}")
    if args.disabled:
        print("\nDisabled:")
        for c in companies:
            if not c.enabled:
                print(f"  {c.name}")
    return 0


def _cmd_audit(_args) -> int:
    from .audit import main as audit_main
    return audit_main()


def _cmd_doctor(_args) -> int:
    """Health-check every enabled company: which can actually produce alerts?"""
    import concurrent.futures as cf

    from . import filters
    from .companies import load_companies
    from .main import _fetch_company

    enabled = [c for c in load_companies(settings.COMPANIES_FILE) if c.enabled]
    dead, silent, healthy = [], [], 0
    with cf.ThreadPoolExecutor(max_workers=settings.CONCURRENCY) as ex:
        for company, jobs, err in ex.map(_fetch_company, enabled):
            if err:
                dead.append(f"{company.name}: {err}")
                continue
            if not jobs:
                dead.append(f"{company.name}: 0 jobs fetched (check token/slug/config)")
                continue
            # matches ignoring recency — "could this company ever alert?"
            m = sum(
                1 for j in jobs
                if filters.matches(j, settings.ROLE_TYPES, settings.OFF_SEASON_ONLY)
                and (not settings.US_CANADA_ONLY
                     or filters.in_north_america(j.location, settings.INCLUDE_UNKNOWN_LOCATIONS))
            )
            if m == 0:
                silent.append(f"{company.name} ({len(jobs)} jobs, none SWE+US/CA right now)")
            else:
                healthy += 1

    print(f"\n{len(enabled)} enabled companies checked:\n")
    print(f"  ✅ {healthy} have matching roles open now (will alert when one is fresh)")
    print(f"  🟡 {len(silent)} fetch fine but have no SWE+US/CA role right now")
    print(f"  ❌ {len(dead)} BROKEN — fetch nothing/error, can never alert\n")
    if dead:
        print("BROKEN (fix these — likely a bad token/slug):")
        for d in dead:
            print(f"  ❌ {d}")
    if silent:
        print("\nNo matching role at the moment (usually fine — off-season):")
        for s in silent[:40]:
            print(f"  🟡 {s}")
    return 1 if dead else 0


def _cmd_discover(args) -> int:
    from .discover import main as discover_main
    return discover_main(args.target)


def _cmd_test_webhook(_args) -> int:
    logger = log.get()
    if not settings.DISCORD_WEBHOOK_URL and not settings.DISCORD_WEBHOOK_URL_ALL:
        logger.error("Neither DISCORD_WEBHOOK_URL nor DISCORD_WEBHOOK_URL_ALL is set.")
        return 2
    from . import notify
    if settings.DISCORD_WEBHOOK_URL:
        notify.notify_summary("🔧 Test message from Internship Radar — your webhook works!")
        logger.info("Test message sent to the main webhook. Check your Discord channel.")
    if settings.DISCORD_WEBHOOK_URL_ALL:
        notify.notify_summary(
            "🔧 Test message from Internship Radar — your all-companies webhook works!",
            webhook_url=settings.DISCORD_WEBHOOK_URL_ALL,
        )
        logger.info("Test message sent to the all-companies webhook. Check your Discord channel.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("run", help="fetch, filter, and notify (default)").set_defaults(fn=_cmd_run)

    pw = sub.add_parser(
        "watch",
        help="poll continuously for new roles (don't wait to be re-invoked)",
    )
    pw.add_argument("--interval", type=int, default=0,
                    help=f"seconds between aggregator polls (default {settings.WATCH_INTERVAL})")
    pw.add_argument("--company-interval", type=int, default=0,
                    help="seconds between full company-ATS sweeps "
                         f"(default {settings.WATCH_COMPANY_INTERVAL})")
    pw.add_argument("--duration", type=int, default=0,
                    help=f"seconds to run before exiting (default {settings.WATCH_DURATION})")
    pw.set_defaults(fn=_cmd_watch)

    pp = sub.add_parser("probe",
                        help="run one adapter against one config and show what it returns")
    pp.add_argument("adapter", help="adapter name, e.g. smartrecruiters")
    pp.add_argument("config", nargs="?", default="",
                    help="key=value pairs separated by ';', e.g. 'id=Atlassian2'")
    pp.add_argument("--name", default="", help="display name to use for the company")
    pp.set_defaults(fn=_cmd_probe)

    pm = sub.add_parser("merge-state",
                        help="union another seen-jobs file into ours (used before pushing state)")
    pm.add_argument("other", help="path to the other seen_jobs.json")
    pm.set_defaults(fn=_cmd_merge_state)

    pl = sub.add_parser("list", help="show tracked companies")
    pl.add_argument("--disabled", action="store_true", help="also list disabled companies")
    pl.set_defaults(fn=_cmd_list)

    sub.add_parser("audit", help="freshness report of past alerts").set_defaults(fn=_cmd_audit)

    sub.add_parser("doctor", help="health-check companies: which can produce alerts?").set_defaults(
        fn=_cmd_doctor)

    pd = sub.add_parser("discover", help="detect a company's ATS config")
    pd.add_argument("target", nargs="+", help="company name(s) or careers URL(s)")
    pd.set_defaults(fn=_cmd_discover)

    sub.add_parser("test-webhook", help="send a test message to Discord").set_defaults(
        fn=_cmd_test_webhook)
    return p


def main(argv: list[str] | None = None) -> int:
    log.configure()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        # No subcommand → default to `run` (keeps `python -m jobscraper` working).
        return _cmd_run(args)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
