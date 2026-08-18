"""
Short daily report (spec §20). Deliberately terse -- max 5 opportunities,
only genuine alerts, no 50-ticker dumps. This module only reads state
(IntelRunResult + the papertrader journal); it never computes anything
that changes the account.
"""

from __future__ import annotations

import csv
import datetime as dt

from intel_engine import CandidateResult, IntelRunResult
from intelligence import config as intel_config
from papertrader import config as pt_config


def _thesis(cand: CandidateResult) -> str:
    bits = []
    if cand.convergence.categories_hit:
        bits.append("+".join(cand.convergence.categories_hit))
    elif cand.opportunity.evidence_for:
        bits.append(cand.opportunity.evidence_for[0])
    else:
        bits.append("no strong evidence yet")
    return f"{cand.early_signal.label}; {', '.join(bits)}."


def _todays_new_and_closed_trades(trade_ids_today: list[str], journal_path) -> tuple[list[dict], list[dict]]:
    if not journal_path.exists():
        return [], []
    with journal_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    new_rows = [r for r in rows if r["event_type"] == "ENTRY" and r["trade_id"] in trade_ids_today]
    today_str = dt.date.today().isoformat()
    closed_rows = [r for r in rows if r["event_type"] == "EXIT" and r["timestamp"].startswith(today_str)]
    return new_rows, closed_rows


def format_intel_report(result: IntelRunResult) -> str:
    L: list[str] = []
    add = L.append

    add("=" * 70)
    add(f"DAILY INTELLIGENCE REPORT -- {result.run_date.isoformat()}")
    add("=" * 70)

    add("\nMARKET REGIME")
    add(f"  {result.regime.regime} (confidence: {result.regime.confidence})")
    for e in result.regime.evidence:
        add(f"    - {e}")
    for chain in result.chains:
        if chain.status in ("CONFIRMED", "PARTIALLY_CONFIRMED"):
            add(f"  Cross-asset chain {chain.status}: {chain.name}")
            for link in chain.links:
                mark = "PASS" if link.holds else "fail"
                add(f"    [{mark}] {link.description} -- {link.detail}")

    add("\nTODAY'S IMPORTANT CATALYSTS")
    if result.today_catalysts:
        for c in result.today_catalysts:
            add(f"  {', '.join(c.tickers)} [{c.impact}] {c.event} -- {c.significance}")
    else:
        add("  None scheduled today.")

    add(f"\nFORWARD RADAR (next {intel_config.CALENDAR_FORWARD_DAYS} days)")
    if result.calendar:
        for c in result.calendar[:10]:
            days_out = (c.date - result.run_date).days
            add(f"  T+{days_out:<2} {c.date.isoformat()} [{c.impact}] {', '.join(c.tickers)}: {c.event}")
    else:
        add("  Nothing on the calendar.")

    add("\nTOP OPPORTUNITIES (max 5)")
    top = [c for c in result.candidates if c.opportunity.alert_level != "NONE"][:5]
    if top:
        for c in top:
            add(
                f"  {c.ticker}  Opp {c.opportunity.score}/100  Early {c.early_signal.score}/100  "
                f"Conv {c.convergence.score}/100  [{c.opportunity.alert_level}]"
            )
            add(f"      {_thesis(c)}")
    else:
        add("  None cleared even the WATCH bar today.")

    add("\n\U0001F6A8 CONVERGENCE ALERTS")
    if result.convergence_alert_candidates:
        for c in result.convergence_alert_candidates:
            add(f"  {c.ticker}: {', '.join(c.convergence.categories_hit)} (score {c.convergence.score}/100)")
            for d in c.convergence.detail:
                add(f"      {d}")
    else:
        add("  None.")

    add("\n\U0001F440 PRE-CATALYST ACTIVITY")
    if result.precatalyst_alerts:
        for a in result.precatalyst_alerts:
            add(f"  {a.ticker}: catalyst in {a.days_until_catalyst}d ({a.catalyst.event}) -- {'; '.join(a.evidence)}")
    else:
        add("  None.")

    add("\n\U0001F433 WHALE FLOW")
    whale_hits = [c for c in result.candidates if c.options and c.options.unusual_contracts]
    if whale_hits:
        for c in whale_hits:
            add(
                f"  {c.ticker}: whale-flow score {c.options.whale_flow_score}/100, "
                f"{c.options.direction_skew}, {len(c.options.unusual_contracts)} elevated contract(s)"
            )
            add(f"      {c.options.caveat}")
    else:
        add("  Nothing genuinely unusual today.")

    add("\nPAPER TRADES")
    new_rows, closed_rows = _todays_new_and_closed_trades(result.executed_trade_ids, pt_config.TRADE_JOURNAL_PATH)
    if new_rows:
        add("  New:")
        for r in new_rows:
            add(f"    {r['ticker']}: {float(r['shares']):.4f} sh @ ${float(r['price']):.2f} "
                f"(${float(r['dollar_amount']):.2f}), stop ${r['stop_loss']}, target ${r['profit_target']}")
    if closed_rows:
        add("  Closed:")
        for r in closed_rows:
            add(f"    {r['ticker']}: P/L ${float(r['pnl_dollars']):+.2f} ({float(r['pnl_pct']):+.2f}%) -- {r['reason_exit']}")
    if result.portfolio.positions:
        add("  Open:")
        for ticker, pos in result.portfolio.positions.items():
            add(f"    {ticker}: {pos.shares:.4f} sh @ ${pos.entry_price:.2f}, stop ${pos.stop_loss}, target ${pos.profit_target}")
    if not new_rows and not closed_rows and not result.portfolio.positions:
        add("  None open, new, or closed today.")

    add("\nTOMORROW")
    near_miss = [
        c for c in result.candidates
        if c.opportunity.alert_level == intel_config.ALERT_HIGH_CONVICTION_WATCH
    ][:3]
    if near_miss:
        add("  Watching for confirmation on: " + ", ".join(
            f"{c.ticker} (opp {c.opportunity.score}, conv {c.convergence.score})" for c in near_miss
        ))
    upcoming = [c for c in result.calendar if (c.date - result.run_date).days == 1]
    if upcoming:
        add("  Catalysts landing tomorrow: " + "; ".join(f"{', '.join(c.tickers)}: {c.event}" for c in upcoming))
    if not near_miss and not upcoming:
        add("  Nothing specific flagged -- routine scan again after next close.")

    add("\nNOISE WE IGNORED")
    if result.noise_ignored:
        for n in result.noise_ignored:
            add(f"  - {n}")
    else:
        add("  Nothing notable rejected today.")

    return "\n".join(L)
