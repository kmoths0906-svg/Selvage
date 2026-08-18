"""
Opportunity Score (spec §13) + alert-level assignment (spec §21).

A high score means INVESTIGATE, not BUY -- actually placing a paper trade
additionally requires clearing the higher, separate bar in
intelligence/config.py (ACTIONABLE_MIN_OPPORTUNITY_SCORE /
ACTIONABLE_MIN_CONVERGENCE_SCORE) AND a genuine convergence alert (>=3
independent categories). Excitement alone never produces a 🔴.

Two inputs are honestly incomplete on free data and are called out rather
than silently defaulted:
  - short-interest risk: no reliable free real-time source (see README) --
    always listed under caveats, never scored.
  - risk/reward: the *actual* stop/target R:R is computed later, at trade
    construction (papertrader.strategy-style ATR stop), not here. This
    score's "setup quality" component is a rough proxy only.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

from catalysts.models import Catalyst, IMPACT_BINARY, IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM
from intelligence import config as intel_config
from intelligence.scanner import ScanResult
from .convergence import ConvergenceResult
from .early_signal import EarlySignalResult

_IMPACT_SCORE = {IMPACT_BINARY: 100, IMPACT_HIGH: 90, IMPACT_MEDIUM: 55, IMPACT_LOW: 25}

_DILUTION_MARKERS = ("S-1 filed", "S-3 filed", "Unregistered sale of equity", "3.02")


@dataclass
class OpportunityResult:
    ticker: str
    score: int
    components: dict[str, float]
    evidence_for: list[str]
    evidence_against: list[str]
    caveats: list[str]
    alert_level: str


def _catalyst_quality_score(catalysts_for_ticker: list[Catalyst], today: dt.date) -> tuple[float, list[str]]:
    recent = [c for c in catalysts_for_ticker if (today - c.date).days <= 10]
    if not recent:
        return 0.0, []
    best = max(recent, key=lambda c: _IMPACT_SCORE.get(c.impact, 0))
    return float(_IMPACT_SCORE.get(best.impact, 0)), [f"Catalyst: {best.event} ({best.impact}, {best.certainty})"]


def score_opportunity(
    scan: ScanResult,
    catalysts_for_ticker: list[Catalyst],
    early_signal: EarlySignalResult,
    convergence: ConvergenceResult,
    today: Optional[dt.date] = None,
) -> OpportunityResult:
    today = today or dt.date.today()
    evidence_for: list[str] = []
    evidence_against: list[str] = []
    caveats: list[str] = ["Short-interest risk: DATA UNAVAILABLE (no reliable free real-time source)."]

    catalyst_score, catalyst_evidence = _catalyst_quality_score(catalysts_for_ticker, today)
    evidence_for.extend(catalyst_evidence)

    liquidity_score = 90.0 if scan.error is None else 0.0
    if scan.error:
        evidence_against.append(f"Scanner data unavailable: {scan.error}")

    volume_score = 0.0
    if scan.rel_volume is not None:
        volume_score = min(100.0, scan.rel_volume / intel_config.REL_VOLUME_HIGH * 100)
        if scan.rel_volume >= intel_config.REL_VOLUME_ELEVATED:
            evidence_for.append(f"Relative volume {scan.rel_volume:.1f}x 20-day average")

    setup_quality_score = 50.0
    if scan.range_breakout:
        setup_quality_score += 20
        evidence_for.append(f"Broke {intel_config.RANGE_BREAKOUT_LOOKBACK_DAYS}-day range high")
    if scan.range_breakdown:
        setup_quality_score -= 20
        evidence_against.append(f"Broke {intel_config.RANGE_BREAKOUT_LOOKBACK_DAYS}-day range low")
    if scan.accum_dist_trend == "DISTRIBUTION":
        setup_quality_score -= 15
        evidence_against.append("Accumulation/distribution line trending down (distribution)")
    setup_quality_score = max(0.0, min(100.0, setup_quality_score))
    caveats.append("Risk/reward here is a rough setup-quality proxy; the actual stop/target R:R "
                    "is computed separately at trade-construction time.")

    dilution_hit = any(
        any(marker in c.event or marker in c.significance for marker in _DILUTION_MARKERS)
        for c in catalysts_for_ticker if (today - c.date).days <= 30
    )
    dilution_penalty = 15.0 if dilution_hit else 0.0
    if dilution_hit:
        evidence_against.append("Recent filing suggests potential dilution (S-1/S-3/unregistered equity sale)")

    if early_signal.score < 40:
        evidence_against.append(f"Early-signal score only {early_signal.score}/100 -- move may already be obvious")
    else:
        evidence_for.append(f"Early-signal score {early_signal.score}/100 ({early_signal.label})")

    if convergence.categories_hit:
        evidence_for.append(f"Convergence: {', '.join(convergence.categories_hit)}")
    else:
        evidence_against.append("No independent evidence categories currently converge on this ticker")

    components = {
        "catalyst_quality": catalyst_score,
        "early_signal": float(early_signal.score),
        "convergence": float(convergence.score),
        "volume_behavior": volume_score,
        "setup_quality": setup_quality_score,
        "liquidity": liquidity_score,
    }
    weights = {
        "catalyst_quality": 0.15, "early_signal": 0.20, "convergence": 0.30,
        "volume_behavior": 0.10, "setup_quality": 0.15, "liquidity": 0.10,
    }
    raw = sum(components[k] * weights[k] for k in components)
    score = max(0.0, raw - dilution_penalty)
    score = round(max(0, min(100, score)))

    alert_level = assign_alert_level(score, convergence)

    return OpportunityResult(scan.ticker, score, components, evidence_for, evidence_against, caveats, alert_level)


def assign_alert_level(opportunity_score: int, convergence: ConvergenceResult) -> str:
    """Spec §21. A 🔴 requires BOTH a high opportunity score AND a genuine
    convergence alert (>=3 independent categories) -- never assigned for
    excitement alone."""
    # No independent evidence category fired at all -> no alert, full
    # stop, regardless of score. Otherwise a ticker with zero real
    # evidence could still clear a low score threshold on baseline
    # components alone (liquidity, generic setup quality) and wrongly
    # show up as "worth watching."
    if not convergence.categories_hit:
        return "NONE"

    if (
        opportunity_score >= intel_config.ACTIONABLE_MIN_OPPORTUNITY_SCORE
        and convergence.score >= intel_config.ACTIONABLE_MIN_CONVERGENCE_SCORE
        and convergence.is_alert
    ):
        return intel_config.ALERT_ACTIONABLE
    if convergence.is_alert or opportunity_score >= 60:
        return intel_config.ALERT_HIGH_CONVICTION_WATCH
    if len(convergence.categories_hit) >= 2 or opportunity_score >= 40:
        return intel_config.ALERT_DEVELOPING
    return intel_config.ALERT_WATCH
