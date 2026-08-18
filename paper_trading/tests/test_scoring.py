from __future__ import annotations

import datetime as dt

from catalysts.models import Catalyst, CERTAINTY_CONFIRMED, IMPACT_HIGH
from intelligence import config as intel_config
from intelligence.macro import RegimeResult
from intelligence.options_lite import OptionsSnapshotResult, UnusualContract
from intelligence.scanner import ScanResult
from intelligence.sectors import SectorStrength
from scoring import convergence, early_signal, opportunity

TODAY = dt.date(2026, 8, 18)


def _scan(**overrides) -> ScanResult:
    base = dict(
        ticker="XYZ", as_of=TODAY, last_close=100.0, rel_volume=None, gap_pct=None,
        ret_3d_pct=1.0, ret_prior_3d_pct=0.5, ret_20d_pct=2.0, price_accelerating=False,
        vol_ratio_recent_vs_prior=None, volume_accelerating=None, range_breakout=False,
        range_breakdown=False, rel_strength_20d_pct=1.0, accum_dist_trend=None, error=None,
    )
    base.update(overrides)
    return ScanResult(**base)


def _catalyst(days_ago: int, impact=IMPACT_HIGH) -> Catalyst:
    return Catalyst(
        TODAY - dt.timedelta(days=days_ago), None, ("XYZ",), "SEC_FILING", "8-K filed",
        "sig", "mech", "src", impact, CERTAINTY_CONFIRMED,
    )


NEUTRAL_REGIME = RegimeResult("MIXED_UNCLEAR", "LOW", [], {}, dt.datetime.now(tz=dt.timezone.utc))


# --------------------------- early_signal ---------------------------

def test_already_moved_a_lot_scores_low():
    scan = _scan(ret_20d_pct=45.0, rel_volume=8.0)
    result = early_signal.score_early_signal(scan, [], options=None, today=TODAY)
    assert result.label == "LIKELY_LATE"


def test_fresh_setup_scores_high():
    scan = _scan(ret_20d_pct=-2.0, rel_volume=2.0, range_breakout=True, ret_3d_pct=3.0, ret_prior_3d_pct=1.0)
    result = early_signal.score_early_signal(scan, [_catalyst(1)], options=None, today=TODAY)
    assert result.label == "LIKELY_EARLY"


def test_scanner_error_yields_insufficient_data():
    scan = _scan(error="insufficient history")
    result = early_signal.score_early_signal(scan, [], options=None, today=TODAY)
    assert result.label == "INSUFFICIENT_DATA"
    assert result.score == 0


# --------------------------- convergence ---------------------------

def test_multiple_scanner_subsignals_count_as_one_category():
    scan = _scan(rel_volume=4.0, range_breakout=True, price_accelerating=True, accum_dist_trend="ACCUMULATION")
    result = convergence.score_convergence("XYZ", scan, [], None, [], NEUTRAL_REGIME, today=TODAY)
    assert result.categories_hit.count("PRICE_VOLUME") == 1


def test_three_independent_categories_trigger_alert():
    scan = _scan(rel_volume=3.0, range_breakout=True)
    sector_strength = SectorStrength("Technology", "XLK", 5.0, 8.0, 4.0, 6.0, True)
    result = convergence.score_convergence(
        "AAPL", scan, [_catalyst(1)], None, [sector_strength], NEUTRAL_REGIME, today=TODAY,
    )
    assert set(result.categories_hit) == {"CATALYST", "PRICE_VOLUME", "SECTOR_STRENGTH"}
    assert result.is_alert is True


def test_two_categories_do_not_trigger_alert():
    scan = _scan(rel_volume=3.0, range_breakout=True)
    result = convergence.score_convergence("AAPL", scan, [_catalyst(1)], None, [], NEUTRAL_REGIME, today=TODAY)
    assert len(result.categories_hit) == 2
    assert result.is_alert is False


def test_options_flow_counts_as_independent_category():
    scan = _scan()
    contract = UnusualContract("XYZ", "2026-09-19", 100.0, "call", 500, 100, 5.0, 20000.0, 0.4)
    options = OptionsSnapshotResult("XYZ", dt.datetime.now(tz=dt.timezone.utc), [contract], 500, 100, "CALL_SKEWED", 60)
    result = convergence.score_convergence("XYZ", scan, [], options, [], NEUTRAL_REGIME, today=TODAY)
    assert "OPTIONS_FLOW" in result.categories_hit


# --------------------------- opportunity / alert level ---------------------------

def test_high_score_and_convergence_alert_yields_actionable():
    # Deliberately stack five independent categories (catalyst, price/volume,
    # sector strength, options flow, macro alignment) -- this is meant to be
    # a rare, everything-lines-up case, not the common one.
    scan = _scan(rel_volume=3.0, range_breakout=True, ret_20d_pct=-2.0, rel_strength_20d_pct=5.0)
    sector_strength = SectorStrength("Technology", "XLK", 5.0, 8.0, 4.0, 6.0, True)
    catalysts = [_catalyst(1)]
    contract = UnusualContract("AAPL", "2026-09-19", 100.0, "call", 500, 100, 5.0, 20000.0, 0.4)
    options = OptionsSnapshotResult("AAPL", dt.datetime.now(tz=dt.timezone.utc), [contract], 500, 100, "CALL_SKEWED", 75)
    risk_on_regime = RegimeResult("RISK_ON", "HIGH", ["broad participation"], {}, dt.datetime.now(tz=dt.timezone.utc))

    conv = convergence.score_convergence("AAPL", scan, catalysts, options, [sector_strength], risk_on_regime, today=TODAY)
    es = early_signal.score_early_signal(scan, catalysts, options, today=TODAY)
    opp = opportunity.score_opportunity(scan, catalysts, es, conv, today=TODAY)

    assert len(conv.categories_hit) >= 4
    assert conv.is_alert is True
    assert opp.alert_level == intel_config.ALERT_ACTIONABLE


def test_no_convergence_never_yields_actionable_even_with_decent_score():
    scan = _scan(rel_volume=3.5, range_breakout=True, ret_20d_pct=-1.0)
    es = early_signal.score_early_signal(scan, [], None, today=TODAY)
    conv = convergence.score_convergence("XYZ", scan, [], None, [], NEUTRAL_REGIME, today=TODAY)
    opp = opportunity.score_opportunity(scan, [], es, conv, today=TODAY)
    assert conv.is_alert is False
    assert opp.alert_level != intel_config.ALERT_ACTIONABLE


def test_dilution_filing_penalizes_score():
    scan = _scan(rel_volume=3.0, range_breakout=True)
    dilution_catalyst = Catalyst(
        TODAY - dt.timedelta(days=1), None, ("XYZ",), "SEC_FILING", "S-1 filed",
        "Registration statement filed -- potential new stock offering.", "Dilution risk.", "src",
        IMPACT_HIGH, CERTAINTY_CONFIRMED,
    )
    es = early_signal.score_early_signal(scan, [dilution_catalyst], None, today=TODAY)
    conv = convergence.score_convergence("XYZ", scan, [dilution_catalyst], None, [], NEUTRAL_REGIME, today=TODAY)
    opp_with = opportunity.score_opportunity(scan, [dilution_catalyst], es, conv, today=TODAY)
    opp_without = opportunity.score_opportunity(scan, [], es, conv, today=TODAY)
    assert opp_with.score < opp_without.score
    assert any("dilution" in e.lower() for e in opp_with.evidence_against)
