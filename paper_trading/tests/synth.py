"""Shared synthetic-data helpers for the intelligence-layer test suite.

geometric_series lets a test specify an exact percent return over an exact
number of trading days (e.g. "+15% over 10 sessions") and get back a full
OHLCV DataFrame with a constant daily growth rate consistent with that --
so ret_5d/ret_10d/ret_20d in the code under test all derive predictably
from one number instead of being hand-tuned per field.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def geometric_series(
    n_bars: int,
    target_return_pct: float,
    over_days: int,
    end: str,
    volume: int = 5_000_000,
    base: float = 100.0,
) -> pd.DataFrame:
    daily_rate = (1 + target_return_pct / 100) ** (1 / over_days) - 1
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n_bars)
    close = base * (1 + daily_rate) ** np.arange(n_bars)
    open_ = np.roll(close, 1)
    open_[0] = close[0] / (1 + daily_rate)
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    vol = np.full(n_bars, volume)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=dates)


def flat_series(n_bars: int, end: str, base: float = 100.0, volume: int = 5_000_000) -> pd.DataFrame:
    return geometric_series(n_bars, 0.0, max(over_days_default(n_bars), 1), end, volume, base)


def over_days_default(n_bars: int) -> int:
    return max(n_bars - 1, 1)


def flat_all(tickers: list[str], n_bars: int, end: str) -> dict[str, pd.DataFrame]:
    return {t: flat_series(n_bars, end) for t in tickers}


def with_volume_spike(df: pd.DataFrame, multiple: float, days: int = 1) -> pd.DataFrame:
    """Return a copy with the last `days` bars' volume multiplied up."""
    out = df.copy()
    out.loc[out.index[-days:], "Volume"] = out["Volume"].iloc[-days:] * multiple
    return out


def recent_acceleration_series(
    n_bars: int, end: str, recent_days: int, recent_pct: float, volume: int = 5_000_000, base: float = 100.0,
) -> pd.DataFrame:
    """Flat until the last `recent_days` bars, which then move
    `recent_pct` -- so nearly all of the return is concentrated recently,
    genuinely "accelerating" rather than a constant daily rate throughout
    (which geometric_series alone can't represent, since a single
    constant rate is sub-linear over sub-windows by construction)."""
    df = flat_series(n_bars, end, base=base, volume=volume)
    anchor_price = float(df["Close"].iloc[-(recent_days + 1)])
    daily_rate = (1 + recent_pct / 100) ** (1 / recent_days) - 1
    for i in range(1, recent_days + 1):
        idx = df.index[-(recent_days + 1) + i]
        close = anchor_price * (1 + daily_rate) ** i
        open_ = anchor_price * (1 + daily_rate) ** (i - 1)
        df.loc[idx, "Close"] = close
        df.loc[idx, "Open"] = open_
        df.loc[idx, "High"] = max(open_, close) * 1.003
        df.loc[idx, "Low"] = min(open_, close) * 0.997
    return df


def with_breakout_high(df: pd.DataFrame, above_pct: float = 5.0) -> pd.DataFrame:
    """Push the last bar's close/high above the prior range so
    range_breakout logic fires; leaves everything else untouched."""
    out = df.copy()
    prior_high = out["High"].iloc[:-1].max()
    new_close = prior_high * (1 + above_pct / 100)
    out.loc[out.index[-1], "Close"] = new_close
    out.loc[out.index[-1], "High"] = new_close * 1.002
    out.loc[out.index[-1], "Open"] = out["Close"].iloc[-2]
    return out
