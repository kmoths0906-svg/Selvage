#!/usr/bin/env python3
"""
CLI entrypoint for the market-intelligence + paper-trading system.

    python run_intel.py daily             # run the full daily intelligence sweep
    python run_intel.py daily --force      # re-run even if already run today

NOTE: this and run_daily.py (the original mechanical-strategy-only
runner) share the same account state file and the same
portfolio.last_run_date flag. Run only ONE of them per day -- whichever
runs first marks the day done and the other will no-op rather than risk
placing two independent sets of trades against the same $130 account on
the same day. Going forward, `daily` here is the intended primary driver;
run_daily.py remains available standalone if you want just the original
pullback strategy with none of the intelligence layer.
"""

from __future__ import annotations

import argparse
import logging
import sys

import learning_db
from intel_engine import run_daily_intelligence
from intel_report import format_intel_report
from intelligence.data_providers import SecEdgarProvider, YFinanceOptionsProvider
from papertrader import config as pt_config
from papertrader.data_source import YFinanceProvider
from papertrader.portfolio import Portfolio


def cmd_daily(args: argparse.Namespace) -> None:
    if not pt_config.PORTFOLIO_STATE_PATH.exists():
        print("No account found. Run `python run_daily.py init` first (same account, shared state).")
        sys.exit(1)

    import datetime as dt
    now = dt.datetime.now(tz=pt_config.TIMEZONE)
    today_str = now.date().isoformat()
    portfolio = Portfolio.load()
    if portfolio.last_run_date == today_str and not args.force:
        print(f"Already ran today ({today_str}); skipping. Pass --force to override.")
        return

    market_provider = YFinanceProvider()
    edgar_provider = SecEdgarProvider()
    options_provider = YFinanceOptionsProvider()
    db_conn = learning_db.get_connection()

    result = run_daily_intelligence(market_provider, edgar_provider, options_provider,
                                     now=now, db_conn=db_conn)
    print(format_intel_report(result))


def main() -> None:
    parser = argparse.ArgumentParser(description="Market intelligence + paper trading runner")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="Run the full daily intelligence sweep")
    p_daily.add_argument("--force", action="store_true", help="Run even if already run today")
    p_daily.set_defaults(func=cmd_daily)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
