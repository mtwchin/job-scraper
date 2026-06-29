"""Unified command-line interface.

    jobscraper run            # fetch, filter, notify (the scheduled command)
    jobscraper list           # show tracked companies + adapter breakdown
    jobscraper audit          # freshness report of past alerts
    jobscraper discover NAME  # detect a company's ATS config
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


def _cmd_discover(args) -> int:
    from .discover import main as discover_main
    return discover_main(args.target)


def _cmd_test_webhook(_args) -> int:
    logger = log.get()
    if not settings.DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL is not set.")
        return 2
    from . import notify
    notify.notify_summary("🔧 Test message from Internship Radar — your webhook works!")
    logger.info("Test message sent. Check your Discord channel.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("run", help="fetch, filter, and notify (default)").set_defaults(fn=_cmd_run)

    pl = sub.add_parser("list", help="show tracked companies")
    pl.add_argument("--disabled", action="store_true", help="also list disabled companies")
    pl.set_defaults(fn=_cmd_list)

    sub.add_parser("audit", help="freshness report of past alerts").set_defaults(fn=_cmd_audit)

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
