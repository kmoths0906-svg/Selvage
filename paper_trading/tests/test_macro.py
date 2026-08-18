from __future__ import annotations

import datetime as dt

from intelligence import macro
from papertrader import config as pt_config
from papertrader.data_source import FakeDataProvider

from .synth import flat_series, geometric_series

NOW = dt.datetime(2026, 8, 17, 16, 30, tzinfo=pt_config.TIMEZONE)
END = "2026-08-14"


def _flat_macro_histories() -> dict:
    return {ticker: flat_series(45, END) for ticker in macro.config.MACRO_TICKERS.values()}


def test_mixed_unclear_when_everything_flat():
    histories = _flat_macro_histories()
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    result = macro.classify_regime(metrics, NOW)
    assert result.regime == "MIXED_UNCLEAR"


def test_energy_shock_detected():
    histories = _flat_macro_histories()
    histories[macro.config.MACRO_TICKERS["wti_crude"]] = geometric_series(45, 15.0, 10, END)
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    result = macro.classify_regime(metrics, NOW)
    assert result.regime == "ENERGY_SHOCK"
    assert "WTI" in result.evidence[0]


def test_risk_on_detected():
    histories = _flat_macro_histories()
    histories[macro.config.MACRO_TICKERS["sp500"]] = geometric_series(45, 3.0, 5, END)
    histories[macro.config.MACRO_TICKERS["nasdaq100"]] = geometric_series(45, 4.0, 5, END)
    histories[macro.config.MACRO_TICKERS["russell2000"]] = geometric_series(45, 2.0, 5, END)
    histories[macro.config.MACRO_TICKERS["vix"]] = geometric_series(45, -10.0, 5, END)
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    result = macro.classify_regime(metrics, NOW)
    assert result.regime == "RISK_ON"


def test_risk_off_detected():
    histories = _flat_macro_histories()
    histories[macro.config.MACRO_TICKERS["sp500"]] = geometric_series(45, -4.0, 5, END)
    histories[macro.config.MACRO_TICKERS["russell2000"]] = geometric_series(45, -7.0, 5, END)
    histories[macro.config.MACRO_TICKERS["vix"]] = geometric_series(45, 25.0, 5, END)
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    result = macro.classify_regime(metrics, NOW)
    assert result.regime == "RISK_OFF"


def test_cross_asset_chain_confirms_when_all_links_hold():
    histories = _flat_macro_histories()
    histories[macro.config.MACRO_TICKERS["wti_crude"]] = geometric_series(45, 8.0, 10, END)
    histories[macro.config.MACRO_TICKERS["gold"]] = geometric_series(45, 3.0, 10, END)
    histories[macro.config.MACRO_TICKERS["us10y_yield"]] = geometric_series(45, 2.0, 10, END)
    histories[macro.config.MACRO_TICKERS["nasdaq100"]] = geometric_series(45, -1.0, 10, END)
    histories[macro.config.MACRO_TICKERS["sp500"]] = geometric_series(45, 1.0, 10, END)
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    chains = macro.check_cross_asset_chains(metrics)
    oil_chain = next(c for c in chains if "Oil shock" in c.name)
    assert oil_chain.status == "CONFIRMED"
    assert all(link.holds for link in oil_chain.links)


def test_cross_asset_chain_not_triggered_without_initial_condition():
    histories = _flat_macro_histories()
    provider = FakeDataProvider(histories, as_of=NOW)
    metrics = macro.fetch_macro_metrics(provider)
    chains = macro.check_cross_asset_chains(metrics)
    oil_chain = next(c for c in chains if "Oil shock" in c.name)
    assert oil_chain.status == "NOT_TRIGGERED"
