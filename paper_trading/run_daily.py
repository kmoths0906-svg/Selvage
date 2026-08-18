#!/usr/bin/env python3
"""
CLI entrypoint for the paper-trading experiment.

    python run_daily.py init             # one-time: create the $130 account
    python run_daily.py run              # do today's exit checks + look for one new entry
    python run_daily.py run --force      # re-run even if already run today (debugging only)
    python run_daily.py report           # print the dashboard (fetches live marks)
    python run_daily.py report --offline # dashboard without a live-price lookup

Intended to be run once per trading day, ideally after 4pm ET (so the
day's daily bar is complete) or before the next open. Running it twice in
one day is a no-op unless --force is passed.
"""

from __future__ import annotations

import argparse
import logging
import sys

from cli_encoding import ensure_utf8_stdio
from papertrader import config, engine, journal, report
from papertrader.data_source import YFinanceProvider
from papertrader.portfolio import Portfolio


def cmd_init(args: argparse.Namespace) -> None:
    if config.PORTFOLIO_STATE_PATH.exists() and not args.reset:
        print(f"Account already initialized at {config.PORTFOLIO_STATE_PATH}. "
              f"Pass --reset to wipe it and start over (this abandons the existing journal).")
        return

    if args.reset:
        confirm = input(
            f"This will reset the account back to ${config.STARTING_CAPITAL:.2f} and "
            "orphan the existing journal history. Type YES to confirm: "
        )
        if confirm.strip() != "YES":
            print("Aborted.")
            return

    portfolio = Portfolio()
    portfolio.save()
    # Touch the CSV logs with headers so they exist even before day 1's run.
    for path, fields in [
        (config.TRADE_JOURNAL_PATH, journal.TRADE_JOURNAL_FIELDS),
        (config.REJECTED_SIGNALS_PATH, journal.REJECTED_SIGNALS_FIELDS),
        (config.EQUITY_CURVE_PATH, journal.EQUITY_CURVE_FIELDS),
    ]:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(",".join(fields) + "\n")

    print(f"Initialized paper account with ${config.STARTING_CAPITAL:.2f} at {config.PORTFOLIO_STATE_PATH}")


def cmd_run(args: argparse.Namespace) -> None:
    if not config.PORTFOLIO_STATE_PATH.exists():
        print("No account found. Run `python run_daily.py init` first.")
        sys.exit(1)
    provider = YFinanceProvider()
    portfolio = engine.run(provider, force=args.force)
    print(f"Run complete for {portfolio.last_run_date}. "
          f"Cash=${portfolio.cash:.2f}, open positions={list(portfolio.positions)}")


def cmd_report(args: argparse.Namespace) -> None:
    provider = None if args.offline else YFinanceProvider()
    r = report.generate_report(provider)
    print(report.format_report(r))


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Paper-trading experiment runner")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create the starting $130 account")
    p_init.add_argument("--reset", action="store_true", help="Wipe existing account state")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="Run today's check for exits and one new entry")
    p_run.add_argument("--force", action="store_true", help="Run even if already run today")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="Print the dashboard")
    p_report.add_argument("--offline", action="store_true", help="Skip live price lookups")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
