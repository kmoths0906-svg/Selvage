"""
Catalyst Pre-Positioning Detector (spec §4). Cross-references the forward
calendar against today's scanner/options output: if a ticker has a known
catalyst coming up AND is already showing unusual activity beforehand,
that combination is exactly the "footprint before the move" this whole
system is built to catch.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from intelligence.scanner import ScanResult
from intelligence.options_lite import OptionsSnapshotResult
from intelligence import config as intel_config
from .models import Catalyst

PRE_CATALYST_LOOKAHEAD_DAYS = 10


@dataclass
class PreCatalystAlert:
    ticker: str
    catalyst: Catalyst
    days_until_catalyst: int
    evidence: list[str]


def detect_pre_catalyst_activity(
    calendar: list[Catalyst],
    scan_results: list[ScanResult],
    options_results: list[OptionsSnapshotResult],
    today: dt.date | None = None,
    lookahead_days: int = PRE_CATALYST_LOOKAHEAD_DAYS,
) -> list[PreCatalystAlert]:
    today = today or dt.date.today()
    scan_by_ticker = {s.ticker: s for s in scan_results}
    options_by_ticker = {o.ticker: o for o in options_results}

    alerts: list[PreCatalystAlert] = []
    for c in calendar:
        days_until = (c.date - today).days
        if not (0 < days_until <= lookahead_days):
            continue

        for ticker in c.tickers:
            evidence: list[str] = []
            scan = scan_by_ticker.get(ticker)
            if scan and scan.error is None:
                if scan.rel_volume and scan.rel_volume >= intel_config.REL_VOLUME_ELEVATED:
                    evidence.append(f"Relative volume {scan.rel_volume:.1f}x 20-day average")
                if scan.range_breakout:
                    evidence.append(f"Broke {intel_config.RANGE_BREAKOUT_LOOKBACK_DAYS}-day high")
                if scan.price_accelerating:
                    evidence.append(
                        f"Price acceleration: 3d return {scan.ret_3d_pct:+.1f}% "
                        f"vs prior 3d {scan.ret_prior_3d_pct:+.1f}%"
                    )
                if scan.accum_dist_trend == "ACCUMULATION":
                    evidence.append("Accumulation/distribution line trending up")

            opts = options_by_ticker.get(ticker)
            if opts and opts.unusual_contracts:
                evidence.append(
                    f"{len(opts.unusual_contracts)} option contract(s) with elevated Vol/OI "
                    f"(whale-flow score {opts.whale_flow_score}/100, {opts.direction_skew})"
                )

            if evidence:
                alerts.append(PreCatalystAlert(
                    ticker=ticker, catalyst=c, days_until_catalyst=days_until, evidence=evidence,
                ))

    return alerts
