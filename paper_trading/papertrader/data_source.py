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

    def prefetch_daily_bars(self, tickers: list[str], lookback_days: int) -> None:
        """
        Optional performance hook: warm an internal cache for a batch of
        tickers in as few network round-trips as possible, so scanning a
        wide universe (hundreds of tickers) doesn't mean hundreds of
        sequential per-ticker fetches. Default is a no-op -- providers
        that have nothing to batch (e.g. FakeDataProvider, which already
        holds everything in memory) simply don't override it.
        get_completed_daily_bars must still work correctly even if this
        was never called; it's a speed optimization, not part of the
        data contract.
        """
        return None


class YFinanceProvider(MarketDataProvider):
    """Free, no-API-key data source backed by Yahoo Finance via yfinance."""

    def __init__(self) -> None:
        import yfinance as yf  # imported lazily so offline tests don't need it

        self._yf = yf
        self._bar_cache: dict[str, pd.DataFrame] = {}
        # Exact count of outbound network calls issued through this
        # provider instance (one per yf.download/Ticker.history call),
        # for auditing request load -- not an estimate.
        self.request_count = 0

    def _now_eastern(self) -> dt.datetime:
        return dt.datetime.now(tz=config.TIMEZONE)

    @staticmethod
    def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.dropna(how="all")

    def _completed_sessions_only(self, df: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
        now = self._now_eastern()
        market_close_today = now.replace(hour=16, minute=0, second=0, microsecond=0)
        today_naive = pd.Timestamp(now.date())
        session_is_complete = (now.weekday() >= 5) or (now >= market_close_today)

        if not session_is_complete:
            df = df[df.index < today_naive]
        else:
            df = df[df.index <= today_naive]

        return df.tail(lookback_days)

    def prefetch_daily_bars(self, tickers: list[str], lookback_days: int, batch_size: int = 100) -> None:
        """Batch-fetch bars for many tickers in a handful of requests
        instead of one-per-ticker, so a wide (hundreds-of-tickers)
        universe stays fast. Best-effort: a failed batch, or a ticker
        missing from a batch's response (e.g. delisted/renamed), is
        silently skipped here -- get_completed_daily_bars() falls back to
        an individual fetch (and ultimately DataUnavailableError) for
        anything that didn't end up in the cache, exactly as if this had
        never been called."""
        period_days = max(lookback_days * 2, lookback_days + 30)
        unique = list(dict.fromkeys(tickers))

        for i in range(0, len(unique), batch_size):
            batch = unique[i:i + batch_size]
            try:
                self.request_count += 1
                raw = self._yf.download(
                    batch, period=f"{period_days}d", interval="1d", progress=False,
                    auto_adjust=False, group_by="ticker", threads=True,
                )
            except Exception:
                continue
            if raw is None or raw.empty:
                continue

            for ticker in batch:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if ticker not in raw.columns.get_level_values(0):
                            continue
                        sub = raw[ticker].copy()
                    else:
                        # A single-ticker batch collapses to a flat frame.
                        sub = raw.copy()
                    sub = self._clean_frame(sub)
                    if not sub.empty:
                        self._bar_cache[ticker] = sub
                except Exception:
                    continue

    def get_completed_daily_bars(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        if ticker in self._bar_cache:
            return self._completed_sessions_only(self._bar_cache[ticker], lookback_days)

        period_days = max(lookback_days * 2, lookback_days + 30)  # pad for weekends/holidays
        self.request_count += 1
        df = self._yf.download(
            ticker,
            period=f"{period_days}d",
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            raise DataUnavailableError(f"No daily bars returned for {ticker!r}")

        df = self._clean_frame(df)
        return self._completed_sessions_only(df, lookback_days)

    def get_latest_price(self, ticker: str) -> Quote:
        t = self._yf.Ticker(ticker)
        price = None
        try:
            self.request_count += 1
            price = t.fast_info.get("last_price")
        except Exception:
            price = None

        if price is None or price != price:  # NaN check
            self.request_count += 1
            hist = t.history(period="1d", interval="1m")
            if hist is None or hist.empty:
                self.request_count += 1
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
