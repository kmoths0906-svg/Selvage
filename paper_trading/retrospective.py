"""
Retrospective testing (spec §17): given a stock that already made a big
move, test whether this system would have found it BEFORE that move,
using only information that was actually available at the simulated time
T. This reuses the exact same FakeDataProvider "as-of cutoff" mechanism
the offline test suite already relies on for the base paper-trading
engine (papertrader/data_source.py) -- the same code path that enforces
no-look-ahead in production enforces it here too.

Scope, honestly stated: Phase 1 retrospective tests can only replay
price/volume evidence (the scanner) and any catalysts YOU explicitly
supply with their real historical filing/announcement dates (e.g. "the
8-K was filed on 2024-03-04") -- there is no historical point-in-time
snapshot of options chains or SEC EDGAR available, so those categories
are DATA UNAVAILABLE in a retrospective test unless you provide them.
Any supplied catalyst dated on/after `as_of` is dropped automatically --
that would be exactly the look-ahead this module exists to prevent.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import learning_db
from catalysts.models import Catalyst
from intelligence import config as intel_config
from intelligence import scanner
from intelligence.macro import RegimeResult
from papertrader import config as pt_config
from papertrader.data_source import FakeDataProvider
from scoring import convergence, early_signal, opportunity

# No historical macro snapshot is available retrospectively (Phase 1), so
# the MACRO_ALIGNMENT convergence category is always neutral/unavailable
# in a retrospective test -- this is not a claim about what the regime
# actually was on that day.
NEUTRAL_REGIME = RegimeResult(
    regime="MIXED_UNCLEAR", confidence="LOW",
    evidence=["Retrospective test: historical macro data not available, category not scored."],
    metrics={}, generated_at=dt.datetime.now(tz=dt.timezone.utc),
)


@dataclass
class RetrospectiveResult:
    ticker: str
    as_of: dt.date
    would_have_found: str          # YES / MAYBE / NO
    scanner_signals: list[str]
    early_signal_score: int
    convergence_score: int
    opportunity_score: int
    categories_hit: list[str]
    false_positive_risks: list[str]
    would_have_passed_rules: bool
    notes: str


def run_retrospective_test(
    ticker: str,
    as_of: dt.date,
    bars_by_ticker: dict[str, pd.DataFrame],
    known_catalysts_before_asof: Optional[list[Catalyst]] = None,
    db_conn=None,
) -> RetrospectiveResult:
    if "SPY" not in bars_by_ticker and ticker != "SPY":
        raise ValueError("bars_by_ticker must include 'SPY' as the benchmark for relative-strength scoring")

    # Anti-hindsight guard: silently trusting caller-supplied catalyst
    # dates would defeat the entire point of this module.
    safe_catalysts = [c for c in (known_catalysts_before_asof or []) if c.date < as_of]
    dropped = len(known_catalysts_before_asof or []) - len(safe_catalysts)

    as_of_dt = dt.datetime.combine(as_of, dt.time(16, 30), tzinfo=pt_config.TIMEZONE)
    provider = FakeDataProvider(bars_by_ticker, as_of=as_of_dt)

    spy_ret_20d = None
    if "SPY" in bars_by_ticker:
        spy_scan = scanner.scan_ticker(provider, "SPY", None)
        spy_ret_20d = spy_scan.ret_20d_pct
    scan = scanner.scan_ticker(provider, ticker, spy_ret_20d)

    scanner_signals = []
    if scan.error is None:
        if scan.rel_volume and scan.rel_volume >= intel_config.REL_VOLUME_ELEVATED:
            scanner_signals.append(f"Relative volume {scan.rel_volume:.1f}x as of {as_of.isoformat()}")
        if scan.range_breakout:
            scanner_signals.append(f"{intel_config.RANGE_BREAKOUT_LOOKBACK_DAYS}d range breakout")
        if scan.price_accelerating:
            scanner_signals.append("Price acceleration")
        if scan.accum_dist_trend == "ACCUMULATION":
            scanner_signals.append("Accumulation/distribution trending up")

    es = early_signal.score_early_signal(scan, safe_catalysts, options=None, today=as_of)
    # No historical options/sector/macro snapshot available in Phase 1 --
    # convergence is computed on catalyst + price/volume evidence only,
    # which understates what the real system (with live options/macro/
    # sector data) would have scored on the actual day.
    conv = convergence.score_convergence(
        ticker, scan, safe_catalysts, options=None, strengthening_sectors=[], regime=NEUTRAL_REGIME, today=as_of,
    )
    opp = opportunity.score_opportunity(scan, safe_catalysts, es, conv, today=as_of)

    if opp.alert_level in (intel_config.ALERT_ACTIONABLE, intel_config.ALERT_HIGH_CONVICTION_WATCH):
        would_have_found = "YES"
    elif opp.alert_level in (intel_config.ALERT_DEVELOPING, intel_config.ALERT_WATCH):
        would_have_found = "MAYBE"
    else:
        would_have_found = "NO"

    false_positive_risks = [
        "Convergence/opportunity scores here are computed WITHOUT historical options or sector/macro "
        "data (unavailable retrospectively) -- the real system would likely score differently, "
        "possibly higher, on the actual day.",
    ]
    if dropped:
        false_positive_risks.append(
            f"{dropped} supplied catalyst(s) were dated on/after as_of and were dropped to prevent look-ahead."
        )
    if scan.error:
        false_positive_risks.append(f"Scanner error: {scan.error}")

    would_have_passed_rules = (
        opp.alert_level == intel_config.ALERT_ACTIONABLE
        and (scan.range_breakout or bool(scan.price_accelerating and (scan.ret_3d_pct or 0) > 0))
    )

    notes = (
        f"Scored as of {as_of.isoformat()} using only bars dated before that day "
        f"(FakeDataProvider cutoff) and {'0' if not safe_catalysts else len(safe_catalysts)} "
        f"caller-supplied pre-{as_of.isoformat()} catalyst(s)."
    )

    if db_conn is not None:
        learning_db.record_retrospective_test(
            db_conn, ticker=ticker, as_of_date=as_of, would_have_found=would_have_found,
            early_signal_score=es.score, convergence_score=conv.score, opportunity_score=opp.score,
            signals_available=scanner_signals, false_positive_risk="; ".join(false_positive_risks),
            would_have_passed_rules=would_have_passed_rules, notes=notes,
        )

    return RetrospectiveResult(
        ticker=ticker, as_of=as_of, would_have_found=would_have_found, scanner_signals=scanner_signals,
        early_signal_score=es.score, convergence_score=conv.score, opportunity_score=opp.score,
        categories_hit=conv.categories_hit, false_positive_risks=false_positive_risks,
        would_have_passed_rules=would_have_passed_rules, notes=notes,
    )
