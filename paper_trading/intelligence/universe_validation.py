"""
Universe validation: is each ticker in CANDIDATE_UNIVERSE still a real,
listed, tradeable security with fresh data?

Design choice worth stating up front: this does NOT run as a separate
periodic sweep that issues its own fetches. It piggybacks on the
scanner.ScanResult objects the daily run already produces for every
non-quarantined ticker -- so validation costs zero extra network
requests. That's the actual mechanism behind "keep a small local
validation cache so we do not waste requests checking every ticker every
day": nothing new is ever requested just to validate; the cache (the
ticker_validation table) is updated from data already in hand, and
QUARANTINED tickers are the only ones excluded from future fetches.

State machine (never removes a ticker after one bad day -- every
transition requires a run of CONSECUTIVE failures, reset to 0 by any
success):

    ACTIVE --(1 failure)--> TEMPORARY_DATA_FAILURE
    TEMPORARY_DATA_FAILURE --(reaches VALIDATION_DELISTED_THRESHOLD)--> POSSIBLY_DELISTED
    (TEMPORARY_DATA_FAILURE | POSSIBLY_DELISTED | STALE)
        --(reaches VALIDATION_QUARANTINE_THRESHOLD)--> QUARANTINED
    (data exists but stale/no volume) --> STALE (same failure-counter ladder as fetch errors)
    any success --> ACTIVE, counters reset

QUARANTINED tickers are excluded from CANDIDATE_UNIVERSE going forward
(filter_active_universe) -- that's the "don't keep wasting requests on
this" behavior. They are NOT rechecked as part of the daily run;
revalidate_quarantined() is a separate, explicitly-invoked, low-frequency
maintenance action (run_intel.py's `revalidate-quarantine` subcommand)
that does issue real fetches, but only for the (small) quarantined list,
and only when a human asks for it.

RENAMED_MERGED is never inferred. There's no free API that reliably maps
an old ticker to its post-rename/merger successor, so guessing one would
violate "do not invent." record_replacement_ticker() is the only way this
status or a replacement_ticker value ever gets set -- always an explicit,
deliberate call (a human, or Claude after doing real research), never
automatic.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import learning_db
from . import config
from .scanner import ScanResult
from papertrader.data_source import DataUnavailableError, MarketDataProvider


def filter_active_universe(conn, tickers: list[str]) -> list[str]:
    """Drop QUARANTINED tickers before scanning -- the one place this
    module actually saves requests, since everything else is free."""
    quarantined = set(learning_db.get_tickers_by_status(conn, learning_db.STATUS_QUARANTINED))
    if not quarantined:
        return tickers
    return [t for t in tickers if t not in quarantined]


def _next_status_on_failure(consecutive_failures: int) -> str:
    if consecutive_failures >= config.VALIDATION_QUARANTINE_THRESHOLD:
        return learning_db.STATUS_QUARANTINED
    if consecutive_failures >= config.VALIDATION_DELISTED_THRESHOLD:
        return learning_db.STATUS_POSSIBLY_DELISTED
    return learning_db.STATUS_TEMPORARY_DATA_FAILURE


def update_validation_from_scan(
    conn, scan_results: list[ScanResult], today: Optional[dt.date] = None
) -> dict[str, str]:
    """Update ticker_validation from ScanResults already produced by
    today's scan. Returns {ticker: new_status} for anything that
    changed status (useful for the daily report / logging newly
    quarantined tickers with their reason and date)."""
    today = today or dt.date.today()
    changed: dict[str, str] = {}

    for s in scan_results:
        prior = learning_db.get_validation_row(conn, s.ticker)
        prior_status = prior["status"] if prior else None
        prior_failures = prior["consecutive_failures"] if prior else 0
        prior_successes = prior["consecutive_successes"] if prior else 0

        if s.error is not None:
            failures = prior_failures + 1
            status = _next_status_on_failure(failures)
            quarantined_at = today if status == learning_db.STATUS_QUARANTINED else None
            quarantine_reason = (
                f"{failures} consecutive data failures as of {today.isoformat()}; "
                f"last error: {s.error}"
                if status == learning_db.STATUS_QUARANTINED else None
            )
            learning_db.upsert_validation(
                conn, ticker=s.ticker, status=status, consecutive_failures=failures,
                consecutive_successes=0, last_checked_date=today, last_error=s.error,
                quarantined_at=quarantined_at, quarantine_reason=quarantine_reason,
            )
        else:
            is_stale = (today - s.as_of).days > config.VALIDATION_STALE_DAYS
            no_volume = s.rel_volume is None  # scanner.py: None means 20d avg volume was <= 0
            if is_stale or no_volume:
                failures = prior_failures + 1
                if failures >= config.VALIDATION_QUARANTINE_THRESHOLD:
                    status = learning_db.STATUS_QUARANTINED
                    quarantined_at = today
                    reason_bits = []
                    if is_stale:
                        reason_bits.append(f"last bar {s.as_of.isoformat()} is >{config.VALIDATION_STALE_DAYS}d old")
                    if no_volume:
                        reason_bits.append("no measurable 20-day average volume")
                    quarantine_reason = (
                        f"{failures} consecutive stale/no-volume readings as of "
                        f"{today.isoformat()}: {', '.join(reason_bits)}"
                    )
                else:
                    status = learning_db.STATUS_STALE
                    quarantined_at = None
                    quarantine_reason = None
                learning_db.upsert_validation(
                    conn, ticker=s.ticker, status=status, consecutive_failures=failures,
                    consecutive_successes=0, last_checked_date=today, last_price=s.last_close,
                    quarantined_at=quarantined_at, quarantine_reason=quarantine_reason,
                )
            else:
                status = learning_db.STATUS_ACTIVE
                learning_db.upsert_validation(
                    conn, ticker=s.ticker, status=status, consecutive_failures=0,
                    consecutive_successes=prior_successes + 1, last_checked_date=today,
                    last_success_date=today, last_price=s.last_close,
                )

        if status != prior_status:
            changed[s.ticker] = status

    return changed


def record_replacement_ticker(
    conn, old_ticker: str, new_ticker: str, note: str, checked_date: Optional[dt.date] = None,
) -> None:
    """The ONLY way RENAMED_MERGED / replacement_ticker ever gets set.
    Always an explicit, deliberate call with a real, verified reason --
    never automatic inference from data patterns."""
    checked_date = checked_date or dt.date.today()
    prior = learning_db.get_validation_row(conn, old_ticker)
    learning_db.upsert_validation(
        conn, ticker=old_ticker, status=learning_db.STATUS_RENAMED_MERGED,
        consecutive_failures=prior["consecutive_failures"] if prior else 0,
        consecutive_successes=0, last_checked_date=checked_date,
        replacement_ticker=new_ticker, notes=note,
    )


def revalidate_quarantined(
    provider: MarketDataProvider, conn, today: Optional[dt.date] = None,
) -> dict[str, str]:
    """Separate, explicitly-invoked, low-frequency maintenance action:
    one real fetch per currently-quarantined ticker to check whether any
    have recovered. Never called automatically by the daily run."""
    today = today or dt.date.today()
    quarantined = learning_db.get_tickers_by_status(conn, learning_db.STATUS_QUARANTINED)
    results: dict[str, str] = {}

    for ticker in quarantined:
        prior = learning_db.get_validation_row(conn, ticker)
        prior_failures = prior["consecutive_failures"] if prior else config.VALIDATION_QUARANTINE_THRESHOLD

        try:
            bars = provider.get_completed_daily_bars(ticker, 10)
            if bars.empty:
                raise DataUnavailableError("empty bars on revalidation")
            as_of = bars.index[-1].date()
            avg_vol = float(bars["Volume"].tail(10).mean())
            is_stale = (today - as_of).days > config.VALIDATION_STALE_DAYS

            if is_stale or avg_vol <= 0:
                learning_db.upsert_validation(
                    conn, ticker=ticker, status=learning_db.STATUS_QUARANTINED,
                    consecutive_failures=prior_failures, consecutive_successes=0,
                    last_checked_date=today,
                    notes=f"Revalidated {today.isoformat()}: still stale/no-volume, remains quarantined.",
                )
                results[ticker] = learning_db.STATUS_QUARANTINED
            else:
                learning_db.upsert_validation(
                    conn, ticker=ticker, status=learning_db.STATUS_ACTIVE,
                    consecutive_failures=0, consecutive_successes=1, last_checked_date=today,
                    last_success_date=today, last_price=float(bars["Close"].iloc[-1]),
                    notes=f"Reinstated from quarantine {today.isoformat()} after successful revalidation.",
                )
                results[ticker] = learning_db.STATUS_ACTIVE
        except DataUnavailableError as e:
            learning_db.upsert_validation(
                conn, ticker=ticker, status=learning_db.STATUS_QUARANTINED,
                consecutive_failures=prior_failures, consecutive_successes=0,
                last_checked_date=today, last_error=str(e),
                notes=f"Revalidated {today.isoformat()}: fetch still fails, remains quarantined.",
            )
            results[ticker] = learning_db.STATUS_QUARANTINED

    return results
