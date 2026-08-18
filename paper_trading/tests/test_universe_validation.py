from __future__ import annotations

import datetime as dt

import learning_db
from intelligence import config as intel_config
from intelligence import universe_validation as uv
from intelligence.scanner import ScanResult
from papertrader.data_source import DataUnavailableError

BASE_DAY = dt.date(2026, 8, 18)


def _scan(ticker: str, error: str | None = None, as_of: dt.date | None = None,
          rel_volume: float | None = 1.0, last_close: float = 100.0) -> ScanResult:
    return ScanResult(
        ticker=ticker, as_of=as_of or BASE_DAY, last_close=last_close, rel_volume=rel_volume,
        gap_pct=None, ret_3d_pct=None, ret_prior_3d_pct=None, ret_20d_pct=None,
        price_accelerating=None, vol_ratio_recent_vs_prior=None, volume_accelerating=None,
        range_breakout=False, range_breakdown=False, rel_strength_20d_pct=None,
        accum_dist_trend=None, error=error,
    )


def _conn(tmp_path):
    return learning_db.get_connection(tmp_path / "learning.db")


def test_single_failure_does_not_quarantine_or_remove(tmp_path):
    conn = _conn(tmp_path)
    uv.update_validation_from_scan(conn, [_scan("XYZ", error="temporary glitch")], today=BASE_DAY)

    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_TEMPORARY_DATA_FAILURE
    assert row["consecutive_failures"] == 1

    active = uv.filter_active_universe(conn, ["XYZ", "ABC"])
    assert active == ["XYZ", "ABC"]  # still scanned tomorrow, not dropped after one bad day


def test_sustained_failures_escalate_through_statuses_then_quarantine(tmp_path):
    conn = _conn(tmp_path)
    day = BASE_DAY
    last_status = None
    for i in range(1, intel_config.VALIDATION_QUARANTINE_THRESHOLD + 1):
        day = day + dt.timedelta(days=1)
        uv.update_validation_from_scan(conn, [_scan("XYZ", error="still broken")], today=day)
        row = learning_db.get_validation_row(conn, "XYZ")
        last_status = row["status"]
        assert row["consecutive_failures"] == i

    assert last_status == learning_db.STATUS_QUARANTINED
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["quarantined_at"] is not None
    assert "consecutive data failures" in row["quarantine_reason"]

    # And now it's excluded from future scans.
    active = uv.filter_active_universe(conn, ["XYZ", "ABC"])
    assert active == ["ABC"]


def test_success_resets_counters_to_active(tmp_path):
    conn = _conn(tmp_path)
    uv.update_validation_from_scan(conn, [_scan("XYZ", error="glitch")], today=BASE_DAY)
    uv.update_validation_from_scan(conn, [_scan("XYZ", error="glitch")], today=BASE_DAY + dt.timedelta(days=1))
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["consecutive_failures"] == 2

    uv.update_validation_from_scan(conn, [_scan("XYZ", error=None)], today=BASE_DAY + dt.timedelta(days=2))
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_ACTIVE
    assert row["consecutive_failures"] == 0
    assert row["consecutive_successes"] == 1
    assert row["last_success_date"] == (BASE_DAY + dt.timedelta(days=2)).isoformat()


def test_stale_data_flagged_without_being_a_hard_failure(tmp_path):
    conn = _conn(tmp_path)
    old_as_of = BASE_DAY - dt.timedelta(days=intel_config.VALIDATION_STALE_DAYS + 3)
    uv.update_validation_from_scan(conn, [_scan("XYZ", as_of=old_as_of)], today=BASE_DAY)
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_STALE


def test_no_volume_flagged_as_stale(tmp_path):
    conn = _conn(tmp_path)
    uv.update_validation_from_scan(conn, [_scan("XYZ", rel_volume=None)], today=BASE_DAY)
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_STALE


def test_replacement_ticker_never_set_automatically(tmp_path):
    conn = _conn(tmp_path)
    day = BASE_DAY
    for i in range(intel_config.VALIDATION_QUARANTINE_THRESHOLD):
        day += dt.timedelta(days=1)
        uv.update_validation_from_scan(conn, [_scan("OLDCO", error="not found")], today=day)

    row = learning_db.get_validation_row(conn, "OLDCO")
    assert row["status"] == learning_db.STATUS_QUARANTINED
    assert row["replacement_ticker"] is None  # never guessed


def test_record_replacement_ticker_is_explicit_and_deliberate(tmp_path):
    conn = _conn(tmp_path)
    uv.update_validation_from_scan(conn, [_scan("OLDCO", error="not found")], today=BASE_DAY)

    uv.record_replacement_ticker(
        conn, "OLDCO", "NEWCO", "Verified via 8-K: OLDCO merged into NEWCO effective 2026-08-01.",
        checked_date=BASE_DAY + dt.timedelta(days=1),
    )
    row = learning_db.get_validation_row(conn, "OLDCO")
    assert row["status"] == learning_db.STATUS_RENAMED_MERGED
    assert row["replacement_ticker"] == "NEWCO"
    assert "merged" in row["notes"]


def test_revalidate_quarantined_reinstates_recovered_ticker(tmp_path):
    conn = _conn(tmp_path)
    day = BASE_DAY
    for i in range(intel_config.VALIDATION_QUARANTINE_THRESHOLD):
        day += dt.timedelta(days=1)
        uv.update_validation_from_scan(conn, [_scan("XYZ", error="broken")], today=day)
    assert learning_db.get_validation_row(conn, "XYZ")["status"] == learning_db.STATUS_QUARANTINED

    class _RecoveredProvider:
        def get_completed_daily_bars(self, ticker, lookback_days):
            import pandas as pd
            dates = pd.bdate_range(end=pd.Timestamp(day), periods=10)
            return pd.DataFrame(
                {"Open": [100.0] * 10, "High": [101.0] * 10, "Low": [99.0] * 10,
                 "Close": [100.0] * 10, "Volume": [1_000_000] * 10},
                index=dates,
            )

    results = uv.revalidate_quarantined(_RecoveredProvider(), conn, today=day)
    assert results["XYZ"] == learning_db.STATUS_ACTIVE
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_ACTIVE
    assert row["consecutive_failures"] == 0


def test_revalidate_quarantined_leaves_still_broken_ticker_quarantined(tmp_path):
    conn = _conn(tmp_path)
    day = BASE_DAY
    for i in range(intel_config.VALIDATION_QUARANTINE_THRESHOLD):
        day += dt.timedelta(days=1)
        uv.update_validation_from_scan(conn, [_scan("XYZ", error="broken")], today=day)

    class _StillBrokenProvider:
        def get_completed_daily_bars(self, ticker, lookback_days):
            raise DataUnavailableError("still 404")

    results = uv.revalidate_quarantined(_StillBrokenProvider(), conn, today=day + dt.timedelta(days=30))
    assert results["XYZ"] == learning_db.STATUS_QUARANTINED
    row = learning_db.get_validation_row(conn, "XYZ")
    assert row["status"] == learning_db.STATUS_QUARANTINED


def test_filter_active_universe_noop_when_nothing_quarantined(tmp_path):
    conn = _conn(tmp_path)
    tickers = ["A", "B", "C"]
    assert uv.filter_active_universe(conn, tickers) == tickers
