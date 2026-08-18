"""
Early-Signal Score (spec §12): are we early, or are we chasing?

0-100, deterministic, built from four components that are each documented
below so the number is auditable, not a black box:
  1. How much the stock has already moved (20d return) -- big penalty if
     the move already happened.
  2. Whether relative volume looks like attention just starting (moderate
     elevation) vs. already exploded (extreme, probably already viral).
  3. Whether there's a fresh catalyst (filed/reported in the last few
     days) that price hasn't fully reacted to yet.
  4. Whether a range breakout, if present, looks fresh vs. already extended.

A quiet stock with several of these can outscore a stock that already
ran 100% -- that's the point of the metric.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from catalysts.models import Catalyst
from intelligence import config as intel_config
from intelligence.scanner import ScanResult
from intelligence.options_lite import OptionsSnapshotResult


@dataclass
class EarlySignalResult:
    ticker: str
    score: int
    label: str   # "LIKELY_EARLY" / "MIXED" / "LIKELY_LATE" / "INSUFFICIENT_DATA"
    reasons: list[str]


def _label(score: int) -> str:
    if score >= 65:
        return "LIKELY_EARLY"
    if score <= 35:
        return "LIKELY_LATE"
    return "MIXED"


def score_early_signal(
    scan: ScanResult,
    catalysts_for_ticker: list[Catalyst],
    options: Optional[OptionsSnapshotResult] = None,
    today: Optional[dt.date] = None,
) -> EarlySignalResult:
    today = today or dt.date.today()
    if scan.error is not None:
        return EarlySignalResult(scan.ticker, 0, "INSUFFICIENT_DATA", [f"Scanner data unavailable: {scan.error}"])

    score = 50
    reasons = [f"Baseline 50."]

    if scan.ret_20d_pct is not None:
        if scan.ret_20d_pct >= intel_config.EARLY_SIGNAL_MOVE_ALREADY_HAPPENED_PCT:
            penalty = min(40, 15 + int(scan.ret_20d_pct))
            score -= penalty
            reasons.append(f"Already up {scan.ret_20d_pct:+.1f}% over 20 sessions -- likely already obvious ({-penalty}).")
        elif scan.ret_20d_pct >= 10:
            score -= 15
            reasons.append(f"Up {scan.ret_20d_pct:+.1f}% over 20 sessions -- partway into the move (-15).")
        elif scan.ret_20d_pct <= 0:
            score += 10
            reasons.append(f"Flat/down over 20 sessions ({scan.ret_20d_pct:+.1f}%) -- no crowd chasing it yet (+10).")
        else:
            score += 5
            reasons.append(f"Modest 20d move ({scan.ret_20d_pct:+.1f}%) -- still early-ish (+5).")

    if scan.rel_volume is not None:
        if 1.5 <= scan.rel_volume < 3.0:
            score += 15
            reasons.append(f"Relative volume {scan.rel_volume:.1f}x -- attention appears to be just starting (+15).")
        elif 3.0 <= scan.rel_volume < 6.0:
            score += 5
            reasons.append(f"Relative volume {scan.rel_volume:.1f}x -- meaningfully elevated already (+5).")
        elif scan.rel_volume >= 6.0:
            score -= 10
            reasons.append(f"Relative volume {scan.rel_volume:.1f}x -- likely already widely noticed (-10).")

    if catalysts_for_ticker:
        most_recent = max(catalysts_for_ticker, key=lambda c: c.date)
        days_since = (today - most_recent.date).days
        reacted_little = scan.ret_3d_pct is not None and abs(scan.ret_3d_pct) < 5
        if days_since <= 2 and reacted_little:
            score += 15
            reasons.append(
                f"Catalyst ({most_recent.event}) is {days_since}d old and price has barely reacted "
                f"(3d return {scan.ret_3d_pct:+.1f}%) -- market may not have repriced it yet (+15)."
            )
        elif days_since <= 5:
            score += 8
            reasons.append(f"Catalyst ({most_recent.event}) is {days_since}d old (+8).")

    if scan.range_breakout:
        if scan.ret_3d_pct is not None and scan.ret_3d_pct < 10:
            score += 10
            reasons.append("Fresh range breakout, not yet extended (+10).")
        else:
            score -= 5
            reasons.append("Range breakout, but already extended over the last 3 sessions (-5).")

    if options and options.unusual_contracts and scan.rel_volume is not None and scan.rel_volume < 3.0:
        score += 5
        reasons.append("Unusual options activity present while stock volume is still only moderately elevated (+5).")

    score = max(0, min(100, score))
    return EarlySignalResult(scan.ticker, score, _label(score), reasons)
