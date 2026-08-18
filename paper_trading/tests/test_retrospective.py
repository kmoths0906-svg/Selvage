from __future__ import annotations

import datetime as dt

from catalysts.models import Catalyst, CERTAINTY_CONFIRMED, IMPACT_HIGH
from retrospective import run_retrospective_test

from .synth import flat_series, recent_acceleration_series, with_breakout_high, with_volume_spike

AS_OF = dt.date(2026, 3, 10)
END = "2026-03-09"


def test_flat_history_yields_no():
    histories = {"XYZ": flat_series(45, END), "SPY": flat_series(45, END)}
    result = run_retrospective_test("XYZ", AS_OF, histories)
    assert result.would_have_found == "NO"


def test_strong_setup_before_move_yields_yes_or_maybe():
    df = recent_acceleration_series(45, END, 5, 6.0)
    df = with_breakout_high(df, above_pct=8.0)
    df = with_volume_spike(df, multiple=4.0, days=1)
    histories = {"XYZ": df, "SPY": flat_series(45, END)}
    catalyst = Catalyst(AS_OF - dt.timedelta(days=1), None, ("XYZ",), "SEC_FILING", "8-K filed",
                         "sig", "mech", "src", IMPACT_HIGH, CERTAINTY_CONFIRMED)
    result = run_retrospective_test("XYZ", AS_OF, histories, known_catalysts_before_asof=[catalyst])
    assert result.would_have_found in ("YES", "MAYBE")
    assert result.scanner_signals  # non-empty: something concrete was found


def test_future_dated_catalyst_is_dropped_anti_hindsight():
    histories = {"XYZ": flat_series(45, END), "SPY": flat_series(45, END)}
    future_catalyst = Catalyst(AS_OF + dt.timedelta(days=2), None, ("XYZ",), "SEC_FILING",
                                "8-K filed AFTER as_of", "sig", "mech", "src", IMPACT_HIGH, CERTAINTY_CONFIRMED)
    result = run_retrospective_test("XYZ", AS_OF, histories, known_catalysts_before_asof=[future_catalyst])
    assert any("dropped" in r.lower() for r in result.false_positive_risks)
    assert "8-K filed AFTER as_of" not in result.notes
