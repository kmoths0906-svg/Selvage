#!/usr/bin/env python3
"""
CLI entrypoint for the market-intelligence + paper-trading system.

    python run_intel.py daily                 # run the full daily intelligence sweep
    python run_intel.py daily --force          # re-run even if already run today
    python run_intel.py daily --diagnostics    # also print a full pipeline audit
    python run_intel.py revalidate-quarantine  # explicit, low-frequency: recheck quarantined tickers

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
import datetime as dt
import logging
import sys
import time

import learning_db
from catalysts import calendar as calendar_mod
from intel_engine import run_daily_intelligence
from intel_report import format_diagnostics, format_intel_report
from intelligence import universe_validation
from intelligence.data_providers import SecEdgarProvider, YFinanceOptionsProvider
from papertrader import config as pt_config
from papertrader.data_source import YFinanceProvider
from papertrader.portfolio import Portfolio


def cmd_daily(args: argparse.Namespace) -> None:
    if not pt_config.PORTFOLIO_STATE_PATH.exists():
        print("No account found. Run `python run_daily.py init` first (same account, shared state).")
        sys.exit(1)

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

    start = time.perf_counter()
    result = run_daily_intelligence(market_provider, edgar_provider, options_provider,
                                     now=now, db_conn=db_conn)
    elapsed = time.perf_counter() - start

    print(format_intel_report(result))
    print(f"\nRuntime: {elapsed:.1f}s")
    print(
        "API requests issued (exact, not estimated): "
        f"market data (yfinance) {market_provider.request_count}, "
        f"SEC EDGAR {edgar_provider.request_count}, "
        f"options (yfinance) {options_provider.request_count}, "
        f"earnings dates (yfinance) {calendar_mod.get_earnings_request_count()}"
    )
    if args.diagnostics:
        print()
        print(format_diagnostics(result))


def cmd_revalidate_quarantine(args: argparse.Namespace) -> None:
    db_conn = learning_db.get_connection()
    quarantined = learning_db.get_tickers_by_status(db_conn, learning_db.STATUS_QUARANTINED)
    if not quarantined:
        print("No quarantined tickers to revalidate.")
        return

    print(f"Revalidating {len(quarantined)} quarantined ticker(s): {', '.join(quarantined)}")
    market_provider = YFinanceProvider()
    results = universe_validation.revalidate_quarantined(market_provider, db_conn)

    reinstated = [t for t, s in results.items() if s == learning_db.STATUS_ACTIVE]
    still_quarantined = [t for t, s in results.items() if s == learning_db.STATUS_QUARANTINED]
    print(f"Reinstated to ACTIVE: {reinstated or 'none'}")
    print(f"Still QUARANTINED: {still_quarantined or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Market intelligence + paper trading runner")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="Run the full daily intelligence sweep")
    p_daily.add_argument("--force", action="store_true", help="Run even if already run today")
    p_daily.add_argument("--diagnostics", action="store_true",
                          help="Also print a full pipeline audit (scan failures, shortlist reasons, cap status)")
    p_daily.set_defaults(func=cmd_daily)

    p_revalidate = sub.add_parser(
        "revalidate-quarantine",
        help="Explicit, low-frequency maintenance: recheck currently-quarantined tickers",
    )
    p_revalidate.set_defaults(func=cmd_revalidate_quarantine)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
