"""
Short daily report (spec §20). Deliberately terse -- max 5 opportunities,
only genuine alerts, no 50-ticker dumps. This module only reads state
(IntelRunResult + the papertrader journal); it never computes anything
that changes the account.
"""

from __future__ import annotations

import csv
import datetime as dt
import json

import learning_db
from intel_engine import CandidateResult, IntelRunResult
from intelligence import config as intel_config
from papertrader import config as pt_config

# The exact emoji used in the report headers below (\U0001F6A8 CONVERGENCE
# ALERTS, \U0001F440 PRE-CATALYST ACTIVITY, \U0001F433 WHALE FLOW). None of
# these encode in cp1252 (Windows' default console code page), which is
# the root cause of the Windows crash cli_encoding.py fixes. Exported so
# tests/test_cli_encoding.py stays tied to what's actually in the report
# rather than a hardcoded string that could silently drift out of sync.
EMOJI_SAMPLE_FOR_TESTS = "\U0001F6A8\U0001F440\U0001F433"


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


def format_diagnostics(result: IntelRunResult) -> str:
    """Full pipeline audit -- NOT part of the terse daily report (§20
    wants that short). Use `python run_intel.py daily --diagnostics` for
    this: every scanned ticker's outcome, exactly which WIDE_UNIVERSE
    tickers were promoted and why, and whether the shortlist cap bound."""
    L: list[str] = []
    add = L.append

    add("=" * 70)
    add("PIPELINE DIAGNOSTICS")
    add("=" * 70)
    add(f"Universe scanned: {result.universe_size} (quarantined excluded: {result.quarantined_count})")
    add(f"Scan failures: {result.failed_count}")
    add(f"WIDE_UNIVERSE tickers flagged notable (pre-cap): {result.wide_notable_count}")
    add(f"Shortlist cap (40) reached: {result.shortlist_cap_reached}")
    add(f"Promoted to enrichment: {result.shortlist_size}")
    add("")

    add("-- Why each shortlisted ticker was promoted --")
    for c in result.candidates:
        basis = ", ".join(c.convergence.categories_hit) if c.convergence.categories_hit else "(no categories -- CORE always enriched)"
        add(f"  {c.ticker}: {basis}")

    add("")
    add("-- Scan failures (ticker: error) --")
    failures = [s for s in result.all_scan_results if s.error is not None]
    if failures:
        for s in failures[:50]:
            add(f"  {s.ticker}: {s.error}")
        if len(failures) > 50:
            add(f"  ... and {len(failures) - 50} more")
    else:
        add("  None.")

    return "\n".join(L)


def format_intel_report(result: IntelRunResult) -> str:
    L: list[str] = []
    add = L.append

    add("=" * 70)
    add(f"DAILY INTELLIGENCE REPORT -- {result.run_date.isoformat()}")
    add("=" * 70)
    add(f"Scanned {result.universe_size} tickers; {result.shortlist_size} promoted to full "
        f"EDGAR/options/scoring enrichment.")
    if result.quarantined_count:
        add(f"({result.quarantined_count} quarantined ticker(s) excluded from this scan -- "
            f"run `python run_intel.py revalidate-quarantine` periodically to recheck them.)")
    if result.validation_status_changes:
        for ticker, status in result.validation_status_changes.items():
            add(f"  Validation status change: {ticker} -> {status}")

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


# ------------------------- Read-only audit reports -------------------------
# Everything below reads existing state (learning.db) and never mutates
# account state, journal, or ticker_validation -- safe to run any number
# of times a day without it counting as "another trading run."

def format_scan_failures(conn, run_date: dt.date) -> str:
    """Item 2 tooling: every ticker whose status wasn't ACTIVE as of
    run_date, with its raw last_error. This does NOT classify WHY a
    ticker failed (delisted/renamed/acquired/temporary) -- that requires
    external research per ticker, which this tool doesn't attempt."""
    rows = conn.execute(
        "SELECT ticker, status, consecutive_failures, last_error, last_checked_date "
        "FROM ticker_validation WHERE last_checked_date=? AND status != ? ORDER BY ticker",
        (run_date.isoformat(), learning_db.STATUS_ACTIVE),
    ).fetchall()

    L = [f"SCAN FAILURES -- {run_date.isoformat()}", "=" * 50]
    if not rows:
        L.append(f"No non-ACTIVE tickers recorded for {run_date.isoformat()} "
                  f"(either everything scanned cleanly, or no run happened this date).")
        return "\n".join(L)

    L.append(f"{len(rows)} ticker(s):\n")
    for r in rows:
        L.append(f"  {r['ticker']:<8} {r['status']:<24} "
                  f"consecutive_failures={r['consecutive_failures']:<3} last_error={r['last_error']}")
    L.append("\nThis is the raw signal only. Classifying DELISTED vs. RENAMED/TICKER_CHANGED vs. "
              "ACQUIRED/TAKEN_PRIVATE vs. TEMPORARY_DATA_FAILURE vs. YFINANCE_ISSUE vs. UNKNOWN "
              "requires researching each ticker individually -- see universe_validation.record_replacement_ticker() "
              "for recording any confirmed rename/merger, which is never done automatically.")
    return "\n".join(L)


def format_funnel_audit(conn, run_date: dt.date) -> str:
    """Item 3 tooling: the full pre-cap WIDE_UNIVERSE ranking (not just
    the tickers that made the cut), so the shortlist cap's actual bite
    can be inspected after the fact."""
    rows = conn.execute(
        "SELECT ticker, tier, quick_score, rank, promoted FROM shortlist_audit "
        "WHERE run_date=? ORDER BY tier ASC, rank ASC",
        (run_date.isoformat(),),
    ).fetchall()

    L = [f"SHORTLIST FUNNEL AUDIT -- {run_date.isoformat()}", "=" * 50]
    if not rows:
        L.append(f"No shortlist_audit rows for {run_date.isoformat()} -- either no run happened "
                  f"this date, or it ran before shortlist_audit existed (this table was added after "
                  f"the first real run; it captures every run from here forward, not retroactively).")
        return "\n".join(L)

    core_rows = [r for r in rows if r["tier"] == "CORE"]
    wide_rows = [r for r in rows if r["tier"] == "WIDE"]
    promoted = [r for r in wide_rows if r["promoted"]]
    excluded = [r for r in wide_rows if not r["promoted"]]

    L.append(f"\nCORE (always enriched, not ranked): {len(core_rows)}")
    L.append("  " + ", ".join(r["ticker"] for r in core_rows))

    L.append(f"\nWIDE_UNIVERSE notable (ranked by quick_score): {len(wide_rows)} total")
    L.append(f"Promoted (cap={intel_config.SHORTLIST_MAX_FROM_WIDE}): {len(promoted)}")
    for r in promoted:
        L.append(f"  #{r['rank']:<3} {r['ticker']:<8} quick_score={r['quick_score']:.1f}")

    L.append(f"\nExcluded by cap: {len(excluded)}")
    for r in excluded:
        L.append(f"  #{r['rank']:<3} {r['ticker']:<8} quick_score={r['quick_score']:.1f}")

    if promoted and excluded:
        gap = promoted[-1]["quick_score"] - excluded[0]["quick_score"]
        L.append(f"\nScore gap at the cutoff (#{promoted[-1]['rank']} vs #{excluded[0]['rank']}): "
                 f"{promoted[-1]['quick_score']:.1f} - {excluded[0]['quick_score']:.1f} = {gap:.1f}")
    elif not excluded:
        L.append(f"\nCap not reached -- every notable WIDE_UNIVERSE ticker was promoted, nothing excluded.")

    return "\n".join(L)


def format_candidate_detail(conn, run_date: dt.date, tickers: list[str]) -> str:
    """Item 4 tooling: full evidence for specific ticker(s) from a given
    day's candidates table -- opportunity/early-signal/convergence
    scores, categories hit, evidence for/against."""
    L = [f"CANDIDATE DETAIL -- {run_date.isoformat()}", "=" * 50]
    for ticker in tickers:
        row = conn.execute(
            "SELECT * FROM candidates WHERE run_date=? AND ticker=? ORDER BY id DESC LIMIT 1",
            (run_date.isoformat(), ticker),
        ).fetchone()
        L.append(f"\n{ticker}")
        if row is None:
            L.append(f"  No candidate row for {ticker} on {run_date.isoformat()} -- "
                      f"either it wasn't shortlisted that day, or no run happened this date.")
            continue
        L.append(f"  Opportunity {row['opportunity_score']}  Early-Signal {row['early_signal_score']}  "
                  f"Convergence {row['convergence_score']}  Alert: {row['alert_level']}")
        L.append(f"  Regime at scoring time: {row['regime']}")
        L.append(f"  Categories hit: {row['categories_hit'] or '(none)'}")
        try:
            evidence_for = json.loads(row["evidence_for"]) if row["evidence_for"] else []
        except (json.JSONDecodeError, TypeError):
            evidence_for = []
        try:
            evidence_against = json.loads(row["evidence_against"]) if row["evidence_against"] else []
        except (json.JSONDecodeError, TypeError):
            evidence_against = []
        if evidence_for:
            L.append("  Evidence for:")
            for e in evidence_for:
                L.append(f"    - {e}")
        if evidence_against:
            L.append("  Evidence against:")
            for e in evidence_against:
                L.append(f"    - {e}")
        if row["trade_id"]:
            L.append(f"  Executed as trade {row['trade_id']}")
    return "\n".join(L)
