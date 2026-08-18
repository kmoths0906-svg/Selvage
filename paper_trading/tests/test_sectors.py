from __future__ import annotations

import datetime as dt

from intelligence import config as intel_config
from intelligence import sectors
from papertrader import config as pt_config
from papertrader.data_source import FakeDataProvider

from .synth import flat_series, geometric_series, recent_acceleration_series

NOW = dt.datetime(2026, 8, 17, 16, 30, tzinfo=pt_config.TIMEZONE)
END = "2026-08-14"


def test_strengthening_sector_detected_and_ranked_first():
    histories = {intel_config.BENCHMARK_TICKER: flat_series(45, END)}
    for sector, ticker in intel_config.SECTOR_ETFS.items():
        histories[ticker] = flat_series(45, END)
    # Energy independently strengthening: flat, then a sharp move
    # concentrated in the last 5 sessions -- genuinely accelerating, not
    # just a steady grind (a constant daily rate is sub-linear over
    # sub-windows, so it would never trip the acceleration check).
    histories["XLE"] = recent_acceleration_series(45, END, recent_days=5, recent_pct=10.0)

    provider = FakeDataProvider(histories, as_of=NOW)
    ranked = sectors.rank_sectors(provider)
    strong = sectors.strengthening_sectors(ranked)

    assert ranked[0].sector == "Energy"
    assert any(s.sector == "Energy" for s in strong)


def test_flat_sector_not_flagged_as_strengthening():
    histories = {intel_config.BENCHMARK_TICKER: flat_series(45, END)}
    for sector, ticker in intel_config.SECTOR_ETFS.items():
        histories[ticker] = flat_series(45, END)

    provider = FakeDataProvider(histories, as_of=NOW)
    ranked = sectors.rank_sectors(provider)
    strong = sectors.strengthening_sectors(ranked)

    assert strong == []
