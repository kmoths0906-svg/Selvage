from __future__ import annotations

from papertrader import config as pt_config
from target_tracker import TARGET_CAPITAL, build_target_tracker_report


def test_required_multiple_and_return_math(tmp_path, monkeypatch):
    monkeypatch.setattr(pt_config, "PORTFOLIO_STATE_PATH", tmp_path / "portfolio_state.json")
    monkeypatch.setattr(pt_config, "TRADE_JOURNAL_PATH", tmp_path / "trade_journal.csv")
    monkeypatch.setattr(pt_config, "EQUITY_CURVE_PATH", tmp_path / "equity_curve.csv")

    report = build_target_tracker_report()

    assert report.starting_capital == pt_config.STARTING_CAPITAL
    assert report.target_capital == TARGET_CAPITAL
    assert abs(report.required_multiple - TARGET_CAPITAL / pt_config.STARTING_CAPITAL) < 0.01
    expected_cum_return = (TARGET_CAPITAL - pt_config.STARTING_CAPITAL) / pt_config.STARTING_CAPITAL * 100
    assert abs(report.required_cumulative_return_pct - expected_cum_return) < 0.5
    # No trades yet -> current balance equals starting capital, 0% actual return.
    assert report.current_balance == pt_config.STARTING_CAPITAL
    assert report.actual_return_pct == 0.0
    # Illustrative trade count should be a real positive number, not None,
    # and risk rules must not have been altered to produce it.
    assert report.illustrative_trades_needed_if_every_trade_won is not None
    assert report.illustrative_trades_needed_if_every_trade_won > 0
    assert report.risk_per_trade_pct == pt_config.MAX_RISK_PER_TRADE_PCT * 100
    assert "not" in report.verdict.lower() or "no real strategy" in report.verdict.lower()
