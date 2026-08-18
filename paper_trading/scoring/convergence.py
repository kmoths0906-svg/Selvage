"""
Convergence Engine (spec §11) -- arguably the most important scoring
module. A single signal should rarely justify a trade; this counts how
many genuinely INDEPENDENT evidence categories agree on a ticker.

The independent categories are deliberately coarse-grained so correlated
measurements don't get counted twice: e.g. elevated relative volume, a
range breakout, and price acceleration are all part of ONE category
("price/volume scanner") because they're all reading the same underlying
phenomenon (unusual trading activity), not three separate pieces of
evidence. The five categories below are chosen to be as causally distinct
as reasonably possible:
  1. CATALYST         -- a real, sourced event (SEC filing / earnings)
  2. PRICE_VOLUME      -- the scanner's price/volume behavior (one category)
  3. OPTIONS_FLOW       -- options positioning (separate data source)
  4. SECTOR_STRENGTH    -- the ticker's sector independently outperforming
  5. MACRO_ALIGNMENT    -- the broad macro regime favoring this kind of asset

A CONVERGENCE ALERT fires only when >= config.CONVERGENCE_MIN_INDEPENDENT_CATEGORIES
(default 3) of these are independently positive.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from catalysts.models import Catalyst
from intelligence import config as intel_config
from intelligence.macro import RegimeResult
from intelligence.scanner import ScanResult
from intelligence.sectors import SectorStrength
from intelligence.options_lite import OptionsSnapshotResult

TICKER_SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "AMD": "Semiconductors", "NVDA": "Semiconductors", "AVGO": "Semiconductors", "SMCI": "Semiconductors",
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "META": "Technology", "JPM": "Financials", "V": "Financials",
    "PLTR": "Technology", "COIN": "Financials",
    "QQQ": "Technology", "SPY": None,
}


@dataclass
class ConvergenceResult:
    ticker: str
    score: int
    categories_hit: list[str]
    detail: list[str]
    is_alert: bool


def score_convergence(
    ticker: str,
    scan: ScanResult,
    catalysts_for_ticker: list[Catalyst],
    options: Optional[OptionsSnapshotResult],
    strengthening_sectors: list[SectorStrength],
    regime: RegimeResult,
    today: Optional[dt.date] = None,
) -> ConvergenceResult:
    today = today or dt.date.today()
    categories: list[str] = []
    detail: list[str] = []

    # 1. CATALYST
    recent_catalysts = [c for c in catalysts_for_ticker if (today - c.date).days <= 5]
    if recent_catalysts:
        categories.append("CATALYST")
        names = ", ".join(c.event for c in recent_catalysts[:3])
        detail.append(f"CATALYST: {names}")

    # 2. PRICE_VOLUME (scanner) -- one category no matter how many sub-signals fire
    scanner_hits = []
    if scan.error is None:
        if scan.rel_volume and scan.rel_volume >= intel_config.REL_VOLUME_ELEVATED:
            scanner_hits.append(f"rel volume {scan.rel_volume:.1f}x")
        if scan.range_breakout:
            scanner_hits.append(f"{intel_config.RANGE_BREAKOUT_LOOKBACK_DAYS}d breakout")
        if scan.price_accelerating:
            scanner_hits.append("price accelerating")
        if scan.accum_dist_trend == "ACCUMULATION":
            scanner_hits.append("accumulation trend")
    if scanner_hits:
        categories.append("PRICE_VOLUME")
        detail.append("PRICE_VOLUME: " + ", ".join(scanner_hits))

    # 3. OPTIONS_FLOW
    if options and options.unusual_contracts:
        categories.append("OPTIONS_FLOW")
        detail.append(
            f"OPTIONS_FLOW: {len(options.unusual_contracts)} elevated contract(s), "
            f"whale-flow score {options.whale_flow_score}/100 ({options.direction_skew}) -- "
            f"free-tier snapshot, not verified sweep data"
        )

    # 4. SECTOR_STRENGTH
    sector = TICKER_SECTOR_MAP.get(ticker)
    if sector and any(s.sector == sector for s in strengthening_sectors):
        categories.append("SECTOR_STRENGTH")
        s = next(s for s in strengthening_sectors if s.sector == sector)
        detail.append(
            f"SECTOR_STRENGTH: {sector} outperforming SPY by {s.rel_strength_20d:+.1f}pp over 20d "
            f"and accelerating"
        )

    # 5. MACRO_ALIGNMENT -- deliberately conservative/generic; only two
    # concrete alignments are checked so this doesn't become a rubber stamp.
    macro_ok = False
    if regime.regime == "RISK_ON" and scan.rel_strength_20d_pct is not None and scan.rel_strength_20d_pct > 0:
        macro_ok = True
        detail.append(
            f"MACRO_ALIGNMENT: RISK_ON regime and {ticker} outperforming SPY by "
            f"{scan.rel_strength_20d_pct:+.1f}pp over 20d"
        )
    elif regime.regime == "ENERGY_SHOCK" and sector == "Energy":
        macro_ok = True
        detail.append(f"MACRO_ALIGNMENT: ENERGY_SHOCK regime and {ticker} is an energy-sector name")
    if macro_ok:
        categories.append("MACRO_ALIGNMENT")

    count = len(categories)
    base = min(count, 5) * 18
    strength_bonus = 0
    if options and options.whale_flow_score >= 70:
        strength_bonus += 5
    if scan.rel_volume and scan.rel_volume >= intel_config.REL_VOLUME_HIGH:
        strength_bonus += 5
    score = max(0, min(100, base + min(strength_bonus, 10)))

    is_alert = count >= intel_config.CONVERGENCE_MIN_INDEPENDENT_CATEGORIES
    return ConvergenceResult(ticker, score, categories, detail, is_alert)
