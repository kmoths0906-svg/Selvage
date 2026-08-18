"""
Tests for YFinanceProvider.prefetch_daily_bars: the batching layer that
keeps a wide (hundreds-of-tickers) universe from meaning hundreds of
sequential network round-trips. Exercised with a fake stand-in for the
`yfinance` module object (no real network involved) so this validates
the MultiIndex-parsing and caching logic itself.
"""

from __future__ import annotations

import pandas as pd
import pytest

from papertrader.data_source import YFinanceProvider


class _FakeYFModule:
    """Minimal stand-in for the yfinance module, recording calls."""

    def __init__(self, download_result=None, raise_on_batch: set[int] | None = None):
        self._result = download_result
        self.download_calls: list[list[str]] = []
        self._raise_on_batch = raise_on_batch or set()

    def download(self, tickers, **kwargs):
        self.download_calls.append(list(tickers) if isinstance(tickers, list) else [tickers])
        if len(self.download_calls) - 1 in self._raise_on_batch:
            raise RuntimeError("simulated network failure")
        return self._result


def _multi_ticker_frame(tickers: list[str], n: int = 45, end: str = "2026-08-10") -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    cols = pd.MultiIndex.from_product([tickers, ["Open", "High", "Low", "Close", "Volume"]])
    data = {}
    for t in tickers:
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            data[(t, c)] = [100.0 if c != "Volume" else 1_000_000] * n
    return pd.DataFrame(data, columns=cols, index=dates)


@pytest.fixture
def provider() -> YFinanceProvider:
    return YFinanceProvider()  # safe: __init__ only imports the yfinance module, no network call


def test_prefetch_populates_cache_and_avoids_second_download(provider):
    tickers = ["AAA", "BBB", "CCC"]
    frame = _multi_ticker_frame(tickers)
    fake = _FakeYFModule(download_result=frame)
    provider._yf = fake

    provider.prefetch_daily_bars(tickers, lookback_days=20)
    assert len(fake.download_calls) == 1  # one batch, three tickers

    bars = provider.get_completed_daily_bars("AAA", lookback_days=20)
    assert not bars.empty
    assert list(bars.columns) == ["Open", "High", "Low", "Close", "Volume"]
    # No second network call: served entirely from the prefetch cache.
    assert len(fake.download_calls) == 1


def test_prefetch_chunks_into_batches(provider):
    tickers = [f"T{i}" for i in range(250)]
    frame = _multi_ticker_frame(tickers[:100])  # only first batch "responds" with real data
    fake = _FakeYFModule(download_result=frame)
    provider._yf = fake

    provider.prefetch_daily_bars(tickers, lookback_days=20, batch_size=100)
    assert len(fake.download_calls) == 3  # 250 tickers / batch_size 100 -> 3 batches
    assert len(fake.download_calls[0]) == 100
    assert len(fake.download_calls[2]) == 50


def test_prefetch_survives_a_failed_batch(provider):
    tickers = ["AAA", "BBB"]
    frame = _multi_ticker_frame(tickers)
    fake = _FakeYFModule(download_result=frame, raise_on_batch={0})
    provider._yf = fake

    # Should not raise even though the (only) batch's download() throws.
    provider.prefetch_daily_bars(tickers, lookback_days=20)
    assert provider._bar_cache == {}


def test_missing_ticker_in_batch_response_falls_back_gracefully(provider):
    # Batch requested for AAA+BBB, but the response only actually contains AAA
    # (simulating a delisted/renamed ticker yfinance silently drops).
    frame = _multi_ticker_frame(["AAA"])
    fake = _FakeYFModule(download_result=frame)
    provider._yf = fake

    provider.prefetch_daily_bars(["AAA", "BBB"], lookback_days=20)
    assert "AAA" in provider._bar_cache
    assert "BBB" not in provider._bar_cache
