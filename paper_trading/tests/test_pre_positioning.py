from __future__ import annotations

import datetime as dt

from catalysts import pre_positioning
from catalysts.models import Catalyst, IMPACT_HIGH, CERTAINTY_CONFIRMED
from intelligence.scanner import ScanResult

TODAY = dt.date(2026, 8, 18)


def _scan(ticker, rel_volume=None, breakout=False, accelerating=False) -> ScanResult:
    return ScanResult(
        ticker=ticker, as_of=TODAY, last_close=100.0, rel_volume=rel_volume, gap_pct=None,
        ret_3d_pct=1.0, ret_prior_3d_pct=0.5, ret_20d_pct=2.0, price_accelerating=accelerating,
        vol_ratio_recent_vs_prior=None, volume_accelerating=None, range_breakout=breakout,
        range_breakdown=False, rel_strength_20d_pct=None, accum_dist_trend=None, error=None,
    )


def _catalyst(ticker, days_out) -> Catalyst:
    return Catalyst(
        TODAY + dt.timedelta(days=days_out), None, (ticker,), "EARNINGS", "earnings", "sig", "mech",
        "src", IMPACT_HIGH, CERTAINTY_CONFIRMED,
    )


def test_alert_fires_when_catalyst_and_unusual_volume_coincide():
    cal = [_catalyst("XYZ", 5)]
    scans = [_scan("XYZ", rel_volume=3.0)]
    alerts = pre_positioning.detect_pre_catalyst_activity(cal, scans, [], today=TODAY)
    assert len(alerts) == 1
    assert alerts[0].ticker == "XYZ"
    assert "volume" in alerts[0].evidence[0].lower()


def test_no_alert_without_unusual_activity():
    cal = [_catalyst("XYZ", 5)]
    scans = [_scan("XYZ", rel_volume=1.0)]
    alerts = pre_positioning.detect_pre_catalyst_activity(cal, scans, [], today=TODAY)
    assert alerts == []


def test_no_alert_when_catalyst_too_far_out():
    cal = [_catalyst("XYZ", 13)]  # beyond the 10-day pre-catalyst lookahead
    scans = [_scan("XYZ", rel_volume=5.0, breakout=True)]
    alerts = pre_positioning.detect_pre_catalyst_activity(cal, scans, [], today=TODAY)
    assert alerts == []


def test_no_alert_for_catalyst_already_in_the_past():
    cal = [_catalyst("XYZ", -1)]
    scans = [_scan("XYZ", rel_volume=5.0, breakout=True)]
    alerts = pre_positioning.detect_pre_catalyst_activity(cal, scans, [], today=TODAY)
    assert alerts == []
