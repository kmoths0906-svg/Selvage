"""
The one strategy used for this experiment: a trend-following pullback
("buy the dip in an uptrend") swing trade, evaluated once per day on
fully-completed daily bars only. See README.md for the full rationale.

`generate_signal` is a pure function of the bars it is handed. It never
reaches out to a data source itself, which is what makes it trivially
auditable for look-ahead bias: give it the same DataFrame and it always
returns the same answer, and that DataFrame is guaranteed by the caller
(engine.py, via data_source.py) to contain no bar later than "now".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import config


@dataclass(frozen=True)
class Signal:
    ticker: str
    generated_at: dt.datetime
    signal_date: pd.Timestamp          # date of the last completed bar used
    reference_close: float             # close on signal_date, for reference only
    planned_stop: float
    planned_target: float
    atr: float
    reason: str


@dataclass(frozen=True)
class Rejection:
    ticker: str
    generated_at: dt.datetime
    reason: str
    detail: str = ""


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    ranges = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def evaluate(
    ticker: str,
    bars: pd.DataFrame,
    now: dt.datetime,
) -> tuple[Optional[Signal], Optional[Rejection]]:
    """
    Apply the pullback strategy to `bars` (completed sessions only, most
    recent last). Returns (Signal, None) or (None, Rejection) -- exactly
    one of the two.
    """

    if len(bars) < config.MIN_BARS_REQUIRED:
        return None, Rejection(
            ticker, now, "insufficient_history",
            f"only {len(bars)} completed bars, need {config.MIN_BARS_REQUIRED}",
        )

    close = bars["Close"]
    last_close = float(close.iloc[-1])

    if last_close < config.MIN_PRICE:
        return None, Rejection(
            ticker, now, "below_min_price", f"close={last_close:.2f}"
        )

    dollar_vol = (bars["Close"] * bars["Volume"]).tail(20).mean()
    if dollar_vol < config.MIN_AVG_DOLLAR_VOLUME:
        return None, Rejection(
            ticker, now, "insufficient_liquidity",
            f"20d avg dollar volume={dollar_vol:,.0f}",
        )

    sma50 = close.rolling(config.TREND_SMA_PERIOD).mean()
    ema10 = close.ewm(span=config.PULLBACK_EMA_PERIOD, adjust=False).mean()
    atr14 = _true_range(bars).rolling(config.ATR_PERIOD).mean()

    sma_now = float(sma50.iloc[-1])
    sma_prior = float(sma50.iloc[-1 - config.TREND_SMA_LOOKBACK_FOR_SLOPE])
    trend_up = (last_close > sma_now) and (sma_now > sma_prior)
    if not trend_up:
        return None, Rejection(
            ticker, now, "no_confirmed_uptrend",
            f"close={last_close:.2f} sma50={sma_now:.2f} "
            f"sma50_{config.TREND_SMA_LOOKBACK_FOR_SLOPE}d_ago={sma_prior:.2f}",
        )

    lookback = bars.iloc[-config.PULLBACK_LOOKBACK_DAYS:]
    ema_over_lookback = ema10.iloc[-config.PULLBACK_LOOKBACK_DAYS:]
    touched_ema = bool((lookback["Low"] <= ema_over_lookback).any())
    if not touched_ema:
        return None, Rejection(
            ticker, now, "no_pullback_to_ema",
            f"low did not touch EMA{config.PULLBACK_EMA_PERIOD} in last "
            f"{config.PULLBACK_LOOKBACK_DAYS} sessions",
        )

    today_open = float(bars["Open"].iloc[-1])
    today_close = last_close
    prev_close = float(close.iloc[-2])
    bullish_reversal = (today_close > today_open) and (today_close > prev_close)
    if not bullish_reversal:
        return None, Rejection(
            ticker, now, "no_bullish_reversal_confirmation",
            f"today open={today_open:.2f} close={today_close:.2f} prev_close={prev_close:.2f}",
        )

    atr = float(atr14.iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None, Rejection(ticker, now, "invalid_atr", f"atr={atr}")

    planned_stop = last_close - config.STOP_ATR_MULT * atr
    risk_per_share = last_close - planned_stop
    planned_target = last_close + config.REWARD_RISK_RATIO * risk_per_share

    if planned_stop <= 0 or risk_per_share <= 0:
        return None, Rejection(ticker, now, "non_positive_stop_distance", f"stop={planned_stop:.2f}")

    reason = (
        f"Uptrend confirmed (close {last_close:.2f} > 50d SMA {sma_now:.2f}, "
        f"SMA rising vs {config.TREND_SMA_LOOKBACK_FOR_SLOPE}d ago); price pulled back "
        f"to touch the {config.PULLBACK_EMA_PERIOD}d EMA within the last "
        f"{config.PULLBACK_LOOKBACK_DAYS} sessions; today closed bullish "
        f"(close {today_close:.2f} > open {today_open:.2f} and > prior close {prev_close:.2f}), "
        f"signalling a resumption of the uptrend. ATR({config.ATR_PERIOD})={atr:.2f}."
    )

    signal = Signal(
        ticker=ticker,
        generated_at=now,
        signal_date=bars.index[-1],
        reference_close=last_close,
        planned_stop=round(planned_stop, 4),
        planned_target=round(planned_target, 4),
        atr=round(atr, 4),
        reason=reason,
    )
    return signal, None
