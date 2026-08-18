"""
Sector Rotation (spec §10): relative strength of each sector ETF against
the SPY benchmark across multiple lookbacks, so a stock's setup can be
weighted higher when its sector is independently strengthening rather
than just moving with the broad tape.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from papertrader.data_source import DataUnavailableError, MarketDataProvider
from . import config


@dataclass
class SectorStrength:
    sector: str
    ticker: str
    ret_5d_pct: Optional[float]
    ret_20d_pct: Optional[float]
    rel_strength_5d: Optional[float]   # sector return - benchmark return
    rel_strength_20d: Optional[float]
    accelerating: Optional[bool]        # 5d relative strength stronger than 20d/4 (i.e. picking up pace)
    error: Optional[str] = None


def _pct_return(bars, days: int) -> Optional[float]:
    if len(bars) < days + 1:
        return None
    close = bars["Close"]
    start = float(close.iloc[-1 - days])
    if start == 0:
        return None
    return round((float(close.iloc[-1]) - start) / start * 100, 3)


def rank_sectors(provider: MarketDataProvider, lookback_days: int = 40) -> list[SectorStrength]:
    try:
        bench_bars = provider.get_completed_daily_bars(config.BENCHMARK_TICKER, lookback_days)
        bench_5d = _pct_return(bench_bars, 5)
        bench_20d = _pct_return(bench_bars, 20)
    except DataUnavailableError as e:
        bench_5d = bench_20d = None
        bench_error = str(e)
    else:
        bench_error = None

    results = []
    for sector, ticker in config.SECTOR_ETFS.items():
        try:
            bars = provider.get_completed_daily_bars(ticker, lookback_days)
            r5 = _pct_return(bars, 5)
            r20 = _pct_return(bars, 20)
            rel5 = round(r5 - bench_5d, 3) if r5 is not None and bench_5d is not None else None
            rel20 = round(r20 - bench_20d, 3) if r20 is not None and bench_20d is not None else None
            accelerating = None
            if rel5 is not None and rel20 is not None:
                # crude pace check: is the trailing-5-day relative strength
                # running hotter than the trailing-20-day average pace?
                accelerating = rel5 > (rel20 / 4)
            err = bench_error
            results.append(SectorStrength(sector, ticker, r5, r20, rel5, rel20, accelerating, err))
        except DataUnavailableError as e:
            results.append(SectorStrength(sector, ticker, None, None, None, None, None, str(e)))

    results.sort(key=lambda s: (s.rel_strength_20d is None, -(s.rel_strength_20d or 0)))
    return results


def strengthening_sectors(ranked: list[SectorStrength]) -> list[SectorStrength]:
    """Sectors independently outperforming the benchmark on both lookbacks
    AND accelerating -- the ones worth weighting a candidate's score up for."""
    return [
        s for s in ranked
        if s.rel_strength_5d is not None and s.rel_strength_20d is not None
        and s.rel_strength_5d > 0 and s.rel_strength_20d > 0 and s.accelerating
    ]
