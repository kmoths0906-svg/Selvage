from __future__ import annotations

import datetime as dt

from catalysts import calendar as calendar_mod
from catalysts.models import IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM, CERTAINTY_CONFIRMED
from intelligence import edgar as edgar_mod
from intelligence.data_providers import FakeEdgarProvider, Filing

TODAY = dt.date(2026, 8, 18)


def _filing(ticker, form_type, filed_date, items=()) -> Filing:
    return Filing(
        ticker=ticker, cik="0000000001", form_type=form_type, filed_date=filed_date,
        accession_number="0000000001-26-000001", primary_doc_url="https://example.invalid/doc.htm",
        items=items, retrieved_at=dt.datetime.now(tz=dt.timezone.utc),
    )


def test_8k_earnings_item_classified_high_impact():
    provider = FakeEdgarProvider({"XYZ": [_filing("XYZ", "8-K", TODAY - dt.timedelta(days=1), items=("2.02", "9.01"))]}, reference_date=TODAY)
    catalysts = edgar_mod.build_edgar_catalysts(provider, ["XYZ"], lookback_days=10)
    assert len(catalysts) == 1
    assert catalysts[0].impact == IMPACT_HIGH
    assert catalysts[0].certainty == CERTAINTY_CONFIRMED
    assert "2.02" in catalysts[0].event


def test_form4_classified_medium_not_assumed_bullish():
    provider = FakeEdgarProvider({"XYZ": [_filing("XYZ", "4", TODAY - dt.timedelta(days=2))]}, reference_date=TODAY)
    catalysts = edgar_mod.build_edgar_catalysts(provider, ["XYZ"], lookback_days=10)
    assert catalysts[0].impact == IMPACT_MEDIUM
    assert "direction" in catalysts[0].transmission_mechanism.lower() or "size" in catalysts[0].transmission_mechanism.lower()


def test_unmapped_item_defaults_low_impact_not_dropped():
    provider = FakeEdgarProvider({"XYZ": [_filing("XYZ", "8-K", TODAY - dt.timedelta(days=1), items=("6.01",))]}, reference_date=TODAY)
    catalysts = edgar_mod.build_edgar_catalysts(provider, ["XYZ"], lookback_days=10)
    assert len(catalysts) == 1
    assert catalysts[0].impact == IMPACT_LOW


def test_filings_outside_lookback_excluded():
    provider = FakeEdgarProvider({"XYZ": [_filing("XYZ", "8-K", TODAY - dt.timedelta(days=30), items=("8.01",))]}, reference_date=TODAY)
    catalysts = edgar_mod.build_edgar_catalysts(provider, ["XYZ"], lookback_days=10)
    assert catalysts == []


def test_calendar_window_filters_correctly():
    from catalysts.models import Catalyst
    in_window = Catalyst(TODAY + dt.timedelta(days=5), None, ("XYZ",), "OTHER", "in window", "sig", "mech", "src", IMPACT_LOW, CERTAINTY_CONFIRMED)
    out_of_window = Catalyst(TODAY + dt.timedelta(days=20), None, ("XYZ",), "OTHER", "too far", "sig", "mech", "src", IMPACT_LOW, CERTAINTY_CONFIRMED)
    past = Catalyst(TODAY - dt.timedelta(days=1), None, ("XYZ",), "OTHER", "past", "sig", "mech", "src", IMPACT_LOW, CERTAINTY_CONFIRMED)

    cal = calendar_mod.build_calendar([in_window, out_of_window, past], [], today=TODAY, forward_days=14, include_seed=False)
    events = [c.event for c in cal]
    assert "in window" in events
    assert "too far" not in events
    assert "past" not in events


def test_earnings_lookup_injected_and_merged():
    def fake_lookup(ticker):
        return [TODAY + dt.timedelta(days=3)] if ticker == "AAPL" else []

    catalysts = calendar_mod.build_earnings_catalysts(["AAPL", "MSFT"], fake_lookup)
    assert len(catalysts) == 1
    assert catalysts[0].tickers == ("AAPL",)
    assert catalysts[0].category == "EARNINGS"
