"""
Market data providers.

The engine only ever talks to a `MarketDataProvider`. That boundary is
what keeps look-ahead bias out of the picture: `get_completed_daily_bars`
is contractually not allowed to return a bar for a session that has not
finished yet, and `get_latest_price` returns whatever the real-time (or
last-traded) quote is *right now*, never a value from the future or a
value we quietly adjust after the fact.

Swap `YFinanceProvider` for a different implementation (e.g. an Alpaca
market-data client) without touching strategy/engine code.
"""

from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass

import pandas as pd

from . import config


class DataUnavailableError(RuntimeError):
    """Raised when a provider cannot return usable data for a ticker."""


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    as_of: dt.datetime  # timezone-aware, when this quote was observed


class MarketDataProvider(abc.ABC):
    """Abstract interface every data source must implement."""

    @abc.abstractmethod
    def get_completed_daily_bars(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        """
        Return a DataFrame indexed by date (ascending) with columns
        Open, High, Low, Close, Volume, containing ONLY sessions that have
        fully closed as of the moment this is called. The most recent
        in-progress session (if the market is currently open) must be
        excluded by the implementation.
        """

    @abc.abstractmethod
    def get_latest_price(self, ticker: str) -> Quote:
        """Return the most recent tradable price available right now."""


class YFinanceProvider(MarketDataProvider):
    """Free, no-API-key data source backed by Yahoo Finance via yfinance."""

    def __init__(self) -> None:
        import yfinance as yf  # imported lazily so offline tests don't need it

        self._yf = yf

    def _now_eastern(self) -> dt.datetime:
        return dt.datetime.now(tz=config.TIMEZONE)

    def get_completed_daily_bars(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        period_days = max(lookback_days * 2, lookback_days + 30)  # pad for weekends/holidays
        df = self._yf.download(
            ticker,
            period=f"{period_days}d",
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            raise DataUnavailableError(f"No daily bars returned for {ticker!r}")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]]
        df.index = pd.to_datetime(df.index).tz_localize(None)

        now = self._now_eastern()
        market_close_today = now.replace(hour=16, minute=0, second=0, microsecond=0)
        today_naive = pd.Timestamp(now.date())
        session_is_complete = (now.weekday() >= 5) or (now >= market_close_today)

        if not session_is_complete:
            df = df[df.index < today_naive]
        else:
            df = df[df.index <= today_naive]

        return df.tail(lookback_days)

    def get_latest_price(self, ticker: str) -> Quote:
        t = self._yf.Ticker(ticker)
        price = None
        try:
            price = t.fast_info.get("last_price")
        except Exception:
            price = None

        if price is None or price != price:  # NaN check
            hist = t.history(period="1d", interval="1m")
            if hist is None or hist.empty:
                hist = t.history(period="5d", interval="1d")
            if hist is None or hist.empty:
                raise DataUnavailableError(f"No live quote available for {ticker!r}")
            price = float(hist["Close"].iloc[-1])

        return Quote(ticker=ticker, price=float(price), as_of=self._now_eastern())


class FakeDataProvider(MarketDataProvider):
    """
    Deterministic in-memory provider for offline testing. Wraps a
    caller-supplied dict of {ticker: full-history DataFrame} plus a
    "current" cursor date, and only ever exposes bars strictly before
    (or through, if after-close) that cursor -- so tests exercise the
    exact same no-look-ahead boundary production code relies on.
    """

    def __init__(self, histories: dict[str, pd.DataFrame], as_of: dt.datetime):
        self._histories = histories
        self.as_of = as_of
        # Optional per-ticker override so tests can simulate a specific
        # live quote (e.g. "price gapped below the stop today") without
        # needing a matching row in the historical bars.
        self.price_overrides: dict[str, float] = {}

    def get_completed_daily_bars(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        df = self._histories[ticker]
        cutoff = pd.Timestamp(self.as_of.date())
        visible = df[df.index < cutoff]
        return visible.tail(lookback_days)

    def get_latest_price(self, ticker: str) -> Quote:
        if ticker in self.price_overrides:
            return Quote(ticker=ticker, price=float(self.price_overrides[ticker]), as_of=self.as_of)
        df = self._histories[ticker]
        cutoff = pd.Timestamp(self.as_of.date())
        row = df[df.index <= cutoff].iloc[-1]
        return Quote(ticker=ticker, price=float(row["Close"]), as_of=self.as_of)
