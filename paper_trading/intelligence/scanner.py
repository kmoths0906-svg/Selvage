"""
Daily Market Scanner (spec §2): per-candidate metrics computed from
completed daily bars only. This module does not score or rank candidates
-- it just measures what actually happened, honestly, so the scoring
layer (scoring/) has real numbers to work from.

Premarket/after-hours volume is best-effort: yfinance's pre/post market
data is free but frequently sparse or a few minutes stale, so it's kept
as an optional bonus signal (fetch_premarket_afterhours_volume) rather
than something the rest of the scanner depends on.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import numpy as np

from papertrader.data_source import DataUnavailableError, MarketDataProvider
from . import config


@dataclass
class ScanResult:
    ticker: str
    as_of: dt.date
    last_close: float
    rel_volume: Optional[float]           # today's volume / 20d avg volume
    gap_pct: Optional[float]               # today's open vs prior close
    ret_3d_pct: Optional[float]
    ret_prior_3d_pct: Optional[float]      # the 3d period before that -- for acceleration
    ret_20d_pct: Optional[float]           # ticker's own absolute 20d return (not relative to SPY)
    price_accelerating: Optional[bool]
    vol_ratio_recent_vs_prior: Optional[float]  # recent 3d avg volume / prior 3d avg volume
    volume_accelerating: Optional[bool]
    range_breakout: bool
    range_breakdown: bool
    rel_strength_20d_pct: Optional[float]  # ticker 20d return - SPY 20d return
    accum_dist_trend: Optional[str]        # "ACCUMULATION" / "DISTRIBUTION" / "FLAT"
    error: Optional[str] = None


def _accumulation_distribution_trend(bars) -> Optional[str]:
    if len(bars) < 15:
        return None
    high, low, close, vol = bars["High"], bars["Low"], bars["Close"], bars["Volume"]
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfv = (mfm.fillna(0) * vol)
    ad_line = mfv.cumsum()
    recent = ad_line.tail(10)
    if len(recent) < 10:
        return None
    slope = np.polyfit(range(len(recent)), recent.values, 1)[0]
    # Normalize against typical traded volume, not the AD line's own
    # magnitude -- a genuinely flat line has an AD value near zero, and
    # dividing by a near-zero scale would blow up ordinary floating-point
    # noise into a false ACCUMULATION/DISTRIBUTION read.
    avg_volume = float(vol.tail(10).mean())
    if avg_volume <= 0:
        return None
    normalized_slope = slope / avg_volume
    if normalized_slope > 0.05:
        return "ACCUMULATION"
    if normalized_slope < -0.05:
        return "DISTRIBUTION"
    return "FLAT"


def scan_ticker(provider: MarketDataProvider, ticker: str, spy_ret_20d: Optional[float]) -> ScanResult:
    def _empty(as_of, last_close, error) -> ScanResult:
        return ScanResult(
            ticker=ticker, as_of=as_of, last_close=last_close,
            rel_volume=None, gap_pct=None, ret_3d_pct=None, ret_prior_3d_pct=None, ret_20d_pct=None,
            price_accelerating=None, vol_ratio_recent_vs_prior=None, volume_accelerating=None,
            range_breakout=False, range_breakdown=False, rel_strength_20d_pct=None,
            accum_dist_trend=None, error=error,
        )

    try:
        bars = provider.get_completed_daily_bars(ticker, config.REL_VOLUME_LOOKBACK_DAYS + 10)
    except DataUnavailableError as e:
        return _empty(dt.date.today(), float("nan"), str(e))

    if len(bars) < 25:
        return _empty(
            bars.index[-1].date() if len(bars) else dt.date.today(),
            float(bars["Close"].iloc[-1]) if len(bars) else float("nan"),
            f"insufficient history ({len(bars)} bars)",
        )

    close, open_, high, low, vol = bars["Close"], bars["Open"], bars["High"], bars["Low"], bars["Volume"]
    last_close = float(close.iloc[-1])
    as_of = bars.index[-1].date()

    avg_vol_20 = float(vol.iloc[-21:-1].mean())
    rel_volume = round(float(vol.iloc[-1]) / avg_vol_20, 3) if avg_vol_20 > 0 else None

    prior_close = float(close.iloc[-2])
    gap_pct = round((float(open_.iloc[-1]) - prior_close) / prior_close * 100, 3) if prior_close else None

    def ret(days_back_start: int, days_back_end: int) -> Optional[float]:
        if len(close) < days_back_start + 1:
            return None
        start = float(close.iloc[-1 - days_back_start])
        end = float(close.iloc[-1 - days_back_end])
        if start == 0:
            return None
        return round((end - start) / start * 100, 3)

    ret_3d = ret(3, 0)
    ret_prior_3d = ret(6, 3)
    price_accelerating = (
        ret_3d is not None and ret_prior_3d is not None and ret_3d > 0 and ret_3d > ret_prior_3d
    )

    recent_vol_avg = float(vol.iloc[-3:].mean())
    prior_vol_avg = float(vol.iloc[-6:-3].mean())
    vol_ratio = round(recent_vol_avg / prior_vol_avg, 3) if prior_vol_avg > 0 else None
    volume_accelerating = vol_ratio is not None and vol_ratio > 1.2

    lookback = config.RANGE_BREAKOUT_LOOKBACK_DAYS
    if len(bars) > lookback:
        prior_high = float(high.iloc[-lookback - 1:-1].max())
        prior_low = float(low.iloc[-lookback - 1:-1].min())
        range_breakout = last_close > prior_high
        range_breakdown = last_close < prior_low
    else:
        range_breakout = range_breakdown = False

    ret_20d = ret(20, 0)
    rel_strength_20d = (
        round(ret_20d - spy_ret_20d, 3) if ret_20d is not None and spy_ret_20d is not None else None
    )

    accum_dist = _accumulation_distribution_trend(bars)

    return ScanResult(
        ticker=ticker, as_of=as_of, last_close=last_close,
        rel_volume=rel_volume, gap_pct=gap_pct,
        ret_3d_pct=ret_3d, ret_prior_3d_pct=ret_prior_3d, ret_20d_pct=ret_20d,
        price_accelerating=price_accelerating,
        vol_ratio_recent_vs_prior=vol_ratio, volume_accelerating=volume_accelerating,
        range_breakout=range_breakout, range_breakdown=range_breakdown,
        rel_strength_20d_pct=rel_strength_20d, accum_dist_trend=accum_dist, error=None,
    )


def scan_universe(provider: MarketDataProvider, tickers: list[str]) -> list[ScanResult]:
    try:
        spy_bars = provider.get_completed_daily_bars(config.BENCHMARK_TICKER, 30)
        spy_ret_20d = None
        if len(spy_bars) >= 21:
            start = float(spy_bars["Close"].iloc[-21])
            spy_ret_20d = round((float(spy_bars["Close"].iloc[-1]) - start) / start * 100, 3) if start else None
    except DataUnavailableError:
        spy_ret_20d = None

    return [scan_ticker(provider, t, spy_ret_20d) for t in tickers]


@dataclass
class PrePostVolume:
    ticker: str
    premarket_volume: Optional[int]
    afterhours_volume: Optional[int]
    retrieved_at: dt.datetime


def fetch_premarket_afterhours_volume(ticker: str) -> Optional[PrePostVolume]:
    """Best-effort only. Returns None (not a fabricated 0) on any failure --
    this data is frequently sparse/unavailable on the free yfinance feed
    outside regular session hours."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=True)
        if hist is None or hist.empty:
            return None
        now_utc = dt.datetime.now(tz=dt.timezone.utc)
        idx = hist.index.tz_convert("America/New_York") if hist.index.tz is not None else hist.index
        pre = hist[(idx.hour < 9) | ((idx.hour == 9) & (idx.minute < 30))]
        post = hist[(idx.hour >= 16)]
        return PrePostVolume(
            ticker=ticker,
            premarket_volume=int(pre["Volume"].sum()) if not pre.empty else None,
            afterhours_volume=int(post["Volume"].sum()) if not post.empty else None,
            retrieved_at=now_utc,
        )
    except Exception:
        return None
