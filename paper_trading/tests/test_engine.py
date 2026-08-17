"""
Offline tests for the trading engine, exercising strategy -> risk sizing
-> execution -> journal logging end to end without any network access,
using FakeDataProvider. These exist because this sandbox's network policy
blocks the real Yahoo Finance endpoints yfinance needs (verified: every
market-data host attempted returns a 403 at the outbound proxy) -- so this
is how the logic gets validated here. Anyone running the real system
locally with normal internet access will exercise the same code path
through YFinanceProvider instead.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from papertrader import config, engine, journal, report, risk, strategy
from papertrader.data_source import FakeDataProvider
from papertrader.portfolio import Portfolio


def _make_uptrend_pullback_series(
    n: int = 70, end: str = "2026-08-14", extra_day_delta: float | None = None
) -> pd.DataFrame:
    """A synthetic series that satisfies the pullback strategy's entry rules
    on its final completed bar: confirmed uptrend, pullback to the 10d EMA
    within the last 3 sessions, bullish reversal on the last day.

    If `extra_day_delta` is given, one more business day is appended after
    the signal day with that close-to-close move, e.g. so a test can give
    the "next session" a decline and confirm the strategy does not
    re-signal a buy off a now-broken setup.
    """
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n - 8):
        close[i] = close[i - 1] + 0.45
    pull = [-0.5, -1.0, -1.5, -2.0, -1.5, -1.0, -0.5, 1.5]
    base = close[n - 9]
    for j, d in enumerate(pull):
        close[n - 8 + j] = base + sum(pull[: j + 1])

    open_ = np.roll(close, 1)
    open_[0] = close[0] - 0.2
    high = np.maximum(open_, close) + 0.3
    low = np.minimum(open_, close) - 0.3
    open_[-1] = close[-2] - 0.3
    high[-1] = max(open_[-1], close[-1]) + 0.2
    low[-1] = min(open_[-1], close[-1]) - 0.4
    volume = np.full(n, 3_000_000)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )

    if extra_day_delta is not None:
        next_date = pd.bdate_range(start=dates[-1] + pd.Timedelta(days=1), periods=1)[0]
        prev_close = close[-1]
        new_close = prev_close + extra_day_delta
        new_open = prev_close
        new_row = pd.DataFrame(
            {
                "Open": [new_open],
                "High": [max(new_open, new_close) + 0.1],
                "Low": [min(new_open, new_close) - 0.1],
                "Close": [new_close],
                "Volume": [3_000_000],
            },
            index=[next_date],
        )
        df = pd.concat([df, new_row])

    return df


def _make_flat_series(n: int = 70, end: str = "2026-08-14") -> pd.DataFrame:
    """A directionless series that should never trigger the strategy."""
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    rng = np.random.default_rng(42)
    close = 50.0 + rng.normal(0, 0.3, size=n).cumsum() * 0.05
    open_ = close - 0.05
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    volume = np.full(n, 3_000_000)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect all persistent state to a temp dir and shrink the universe
    to two synthetic tickers so the test is deterministic and fast."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PORTFOLIO_STATE_PATH", tmp_path / "portfolio_state.json")
    monkeypatch.setattr(config, "TRADE_JOURNAL_PATH", tmp_path / "trade_journal.csv")
    monkeypatch.setattr(config, "REJECTED_SIGNALS_PATH", tmp_path / "rejected_signals.csv")
    monkeypatch.setattr(config, "EQUITY_CURVE_PATH", tmp_path / "equity_curve.csv")
    monkeypatch.setattr(config, "UNIVERSE", ["TEST_BUY", "TEST_FLAT"])
    monkeypatch.setattr(config, "MAX_OPEN_POSITIONS", 2)
    return tmp_path


def test_strategy_rejects_flat_series():
    df = _make_flat_series()
    now = dt.datetime.now(tz=config.TIMEZONE)
    signal, rejection = strategy.evaluate("TEST_FLAT", df, now)
    assert signal is None
    assert rejection is not None
    assert rejection.reason in {"no_confirmed_uptrend", "no_pullback_to_ema", "no_bullish_reversal_confirmation"}


def test_strategy_accepts_pullback_series():
    df = _make_uptrend_pullback_series()
    now = dt.datetime.now(tz=config.TIMEZONE)
    signal, rejection = strategy.evaluate("TEST_BUY", df, now)
    assert rejection is None
    assert signal is not None
    assert signal.planned_stop < signal.reference_close < signal.planned_target


def test_position_sizing_never_exceeds_two_percent_risk():
    result = risk.size_position(equity=130.0, cash=130.0, entry_price=120.95, stop_price=118.71)
    assert result.accepted
    assert result.dollars_at_risk <= 130.0 * config.MAX_RISK_PER_TRADE_PCT + 0.01


def test_position_sizing_respects_cash_reserve():
    # Cash reserve is 10% of equity; a huge equity/tiny-cash mismatch
    # should get capped by cash, not blow through the reserve.
    result = risk.size_position(equity=1000.0, cash=15.0, entry_price=50.0, stop_price=49.0)
    reserve = 1000.0 * config.MIN_CASH_RESERVE_PCT
    assert result.position_value <= max(15.0 - reserve, 0.0) + 0.01


def test_engine_end_to_end_entry_then_stop_loss_exit(sandbox):
    # The extra day (a decline right after the signal day) represents the
    # session that actually happens between day1's decision and day2's
    # run, so day2 sees a broken setup and correctly does NOT re-signal a
    # buy on the same ticker right after being stopped out of it.
    buy_bars = _make_uptrend_pullback_series(end="2026-08-14", extra_day_delta=-2.0)
    flat_bars = _make_flat_series(end="2026-08-14")
    histories = {"TEST_BUY": buy_bars, "TEST_FLAT": flat_bars}

    day1 = dt.datetime(2026, 8, 17, 16, 30, tzinfo=config.TIMEZONE)  # Monday, after close
    provider = FakeDataProvider(histories, as_of=day1)

    portfolio = engine.run(provider, now=day1)

    assert "TEST_BUY" in portfolio.positions
    assert "TEST_FLAT" not in portfolio.positions
    pos = portfolio.positions["TEST_BUY"]
    assert pos.stop_loss < pos.entry_price < pos.profit_target

    equity_at_entry = portfolio.equity({"TEST_BUY": pos.entry_price})
    dollars_at_risk = (pos.entry_price - pos.stop_loss) * pos.shares
    assert dollars_at_risk <= equity_at_entry * config.MAX_RISK_PER_TRADE_PCT + 0.05

    journal_rows_after_entry = list(
        __import__("csv").DictReader(open(config.TRADE_JOURNAL_PATH))
    )
    assert any(r["event_type"] == "ENTRY" and r["ticker"] == "TEST_BUY" for r in journal_rows_after_entry)

    rejected_rows = list(__import__("csv").DictReader(open(config.REJECTED_SIGNALS_PATH)))
    assert any(r["ticker"] == "TEST_FLAT" for r in rejected_rows)

    # Day 2: price gaps below the stop -> engine should close the position.
    day2 = dt.datetime(2026, 8, 18, 16, 30, tzinfo=config.TIMEZONE)
    provider.as_of = day2
    provider.price_overrides["TEST_BUY"] = pos.stop_loss - 0.50

    portfolio2 = engine.run(provider, now=day2)
    assert "TEST_BUY" not in portfolio2.positions
    assert portfolio2.realized_pnl < 0  # stopped out for a loss, as expected

    journal_rows = list(__import__("csv").DictReader(open(config.TRADE_JOURNAL_PATH)))
    exit_rows = [r for r in journal_rows if r["event_type"] == "EXIT"]
    assert len(exit_rows) == 1
    assert "Stop-loss hit" in exit_rows[0]["reason_exit"]

    r = report.generate_report(provider=None)
    assert r.num_trades == 1
    assert r.losses == 1
    assert r.wins == 0
    assert r.starting_balance == config.STARTING_CAPITAL


def test_engine_is_idempotent_within_same_day(sandbox):
    buy_bars = _make_uptrend_pullback_series(end="2026-08-14")
    flat_bars = _make_flat_series(end="2026-08-14")
    histories = {"TEST_BUY": buy_bars, "TEST_FLAT": flat_bars}
    day1 = dt.datetime(2026, 8, 17, 16, 30, tzinfo=config.TIMEZONE)
    provider = FakeDataProvider(histories, as_of=day1)

    engine.run(provider, now=day1)
    portfolio_after_first = Portfolio.load()
    engine.run(provider, now=day1)  # same day, no --force
    portfolio_after_second = Portfolio.load()

    assert portfolio_after_first.trade_counter == portfolio_after_second.trade_counter
