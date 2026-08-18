"""
14-Day Forward Catalyst Calendar (spec §3).

Merges three sources into one sorted, filtered view:
  - the hand-researched macro seed (FOMC/CPI/PPI/jobs -- see macro_calendar_seed.py)
  - live earnings dates per candidate ticker (yfinance, best-effort)
  - EDGAR filing catalysts already filed (from intelligence/edgar.py)

Nothing here covers FDA/biotech dates, index-addition dates, or lockup
expirations for Phase 1 -- there is no reliable free source for those
(see README). They will show as simply absent, not as a fabricated guess.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from .models import Catalyst, IMPACT_HIGH, CERTAINTY_LIKELY
from .macro_calendar_seed import SEED_CATALYSTS
from intelligence import config as intel_config

EarningsLookup = Callable[[str], list[dt.date]]

# Free function, not a provider instance, so the request counter lives at
# module scope -- one process per CLI run, so this starts at 0 naturally.
_earnings_request_count = 0


def get_earnings_request_count() -> int:
    return _earnings_request_count


def yfinance_earnings_lookup(ticker: str) -> list[dt.date]:
    """Real implementation. Best-effort: yfinance's earnings-date data is
    sourced from third parties and can be missing or wrong; failures
    return an empty list rather than raising, since a calendar with a
    gap is far better than a calendar that crashes."""
    global _earnings_request_count
    try:
        import yfinance as yf
        _earnings_request_count += 1
        df = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if df is None or df.empty:
            return []
        return [d.date() for d in df.index if d.date() >= dt.date.today()]
    except Exception:
        return []


def build_earnings_catalysts(tickers: list[str], lookup: EarningsLookup) -> list[Catalyst]:
    now = dt.datetime.now(tz=dt.timezone.utc)
    catalysts = []
    for ticker in tickers:
        for edate in lookup(ticker):
            catalysts.append(Catalyst(
                date=edate, time_et=None, tickers=(ticker,), category="EARNINGS",
                event=f"{ticker} earnings report",
                significance=f"{ticker} scheduled to report earnings.",
                transmission_mechanism=(
                    "Earnings and guidance are a primary near-term repricing catalyst; "
                    "surprises vs. consensus (and forward guidance) tend to move the stock "
                    "most, more than the reported numbers themselves."
                ),
                source="yfinance (third-party earnings calendar; date per data provider, "
                       "subject to change until the company confirms)",
                impact=IMPACT_HIGH, certainty=CERTAINTY_LIKELY, retrieved_at=now,
            ))
    return catalysts


def build_calendar(
    edgar_catalysts: list[Catalyst],
    earnings_catalysts: list[Catalyst],
    today: Optional[dt.date] = None,
    forward_days: int = intel_config.CALENDAR_FORWARD_DAYS,
    include_seed: bool = True,
) -> list[Catalyst]:
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=forward_days)

    all_catalysts = list(edgar_catalysts) + list(earnings_catalysts)
    if include_seed:
        all_catalysts += SEED_CATALYSTS

    windowed = [c for c in all_catalysts if today <= c.date <= horizon]
    windowed.sort(key=lambda c: (c.date, c.tickers))
    return windowed


def today_catalysts(calendar: list[Catalyst], today: Optional[dt.date] = None) -> list[Catalyst]:
    today = today or dt.date.today()
    return [c for c in calendar if c.date == today]
