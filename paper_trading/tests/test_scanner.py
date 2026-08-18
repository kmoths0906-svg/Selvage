from __future__ import annotations

import datetime as dt

from intelligence import scanner
from papertrader import config as pt_config
from papertrader.data_source import FakeDataProvider

from .synth import flat_series, recent_acceleration_series, with_breakout_high, with_volume_spike

NOW = dt.datetime(2026, 8, 17, 16, 30, tzinfo=pt_config.TIMEZONE)
END = "2026-08-14"


def test_flat_ticker_no_signals():
    df = flat_series(35, END)
    provider = FakeDataProvider({"XYZ": df, "SPY": df}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.error is None
    assert result.range_breakout is False
    assert result.range_breakdown is False
    assert not (result.rel_volume and result.rel_volume >= 1.5)


def test_volume_spike_detected_as_elevated_rel_volume():
    df = with_volume_spike(flat_series(35, END), multiple=4.0, days=1)
    provider = FakeDataProvider({"XYZ": df, "SPY": flat_series(35, END)}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.rel_volume is not None and result.rel_volume >= 3.0


def test_range_breakout_detected():
    df = with_breakout_high(flat_series(35, END), above_pct=6.0)
    provider = FakeDataProvider({"XYZ": df, "SPY": flat_series(35, END)}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.range_breakout is True
    assert result.range_breakdown is False


def test_price_acceleration_detected():
    df = recent_acceleration_series(35, END, recent_days=3, recent_pct=8.0)
    provider = FakeDataProvider({"XYZ": df, "SPY": flat_series(35, END)}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.price_accelerating is True
    assert result.ret_3d_pct > result.ret_prior_3d_pct


def test_relative_strength_vs_spy():
    df = recent_acceleration_series(35, END, recent_days=20, recent_pct=15.0)
    provider = FakeDataProvider({"XYZ": df, "SPY": flat_series(35, END)}, as_of=NOW)
    spy_scan = scanner.scan_ticker(provider, "SPY", spy_ret_20d=None)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=spy_scan.ret_20d_pct or 0.0)
    assert result.rel_strength_20d_pct is not None
    assert result.rel_strength_20d_pct > 10.0


def test_flat_series_does_not_falsely_flag_accumulation_or_distribution():
    # Regression test: a perfectly flat series has a near-zero A/D line,
    # and normalizing the slope against the line's own magnitude (instead
    # of against traded volume) let floating-point noise get amplified
    # into a false ACCUMULATION/DISTRIBUTION read.
    df = flat_series(35, END)
    provider = FakeDataProvider({"XYZ": df, "SPY": df}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.accum_dist_trend == "FLAT"


def test_is_notable_true_for_elevated_volume():
    df = with_volume_spike(flat_series(35, END), multiple=4.0, days=1)
    provider = FakeDataProvider({"XYZ": df, "SPY": flat_series(35, END)}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert scanner.is_notable(result) is True
    assert scanner.quick_score(result) > 0


def test_is_notable_false_for_flat_ticker():
    df = flat_series(35, END)
    provider = FakeDataProvider({"XYZ": df, "SPY": df}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert scanner.is_notable(result) is False
    assert scanner.quick_score(result) == 0.0


def test_is_notable_false_and_zero_score_on_scanner_error():
    df = flat_series(5, END)  # too short -> error
    provider = FakeDataProvider({"XYZ": df, "SPY": df}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.error is not None
    assert scanner.is_notable(result) is False
    assert scanner.quick_score(result) == 0.0


def test_quick_score_ranks_stronger_setup_higher():
    weak = with_volume_spike(flat_series(35, END), multiple=1.6, days=1)
    strong_df = with_breakout_high(flat_series(35, END), above_pct=6.0)
    strong_df = with_volume_spike(strong_df, multiple=5.0, days=1)
    provider = FakeDataProvider({"WEAK": weak, "STRONG": strong_df, "SPY": flat_series(35, END)}, as_of=NOW)
    weak_result = scanner.scan_ticker(provider, "WEAK", spy_ret_20d=0.0)
    strong_result = scanner.scan_ticker(provider, "STRONG", spy_ret_20d=0.0)
    assert scanner.quick_score(strong_result) > scanner.quick_score(weak_result)


def test_insufficient_history_reports_error_not_crash():
    df = flat_series(10, END)
    provider = FakeDataProvider({"XYZ": df, "SPY": df}, as_of=NOW)
    result = scanner.scan_ticker(provider, "XYZ", spy_ret_20d=0.0)
    assert result.error is not None
