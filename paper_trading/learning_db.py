"""
Learning database (spec §18): SQLite record of every candidate, alert,
convergence alert, pre-catalyst alert, rejected candidate, social-media
verification, and retrospective test -- plus the joins needed to measure
which signals actually predict anything.

Why SQLite and not another CSV: §18 explicitly wants win rate / expectancy
broken down by signal type, catalyst type, sector, regime, and convergence
combination. That's real groupby analysis, and CSV-scanning for it gets
painful fast. This stays a single file (stdlib sqlite3, nothing to
install) and never touches the existing papertrader/data/trade_journal.csv
-- trades remain the CSV journal's job; this database links to them by
trade_id so performance can be joined back to the evidence that produced
each trade.

Honesty note: with zero completed paper trades so far, the grouped
performance functions below will return empty/near-empty results. That's
correct, not a bug -- see compute_overall_performance()'s docstring.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Optional

from intelligence import config as intel_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    opportunity_score INTEGER,
    early_signal_score INTEGER,
    convergence_score INTEGER,
    alert_level TEXT,
    regime TEXT,
    categories_hit TEXT,
    evidence_for TEXT,
    evidence_against TEXT,
    trade_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS convergence_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    convergence_score INTEGER,
    categories_hit TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS precatalyst_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    catalyst_event TEXT,
    catalyst_date TEXT,
    days_until INTEGER,
    evidence TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    opportunity_score INTEGER,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS social_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_text TEXT NOT NULL,
    ticker TEXT,
    source_platform TEXT,
    claim_public_at TEXT,
    verified_at TEXT NOT NULL,
    classification TEXT,
    scanner_would_have_found INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS retrospective_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    would_have_found TEXT,
    early_signal_score INTEGER,
    convergence_score INTEGER,
    opportunity_score INTEGER,
    signals_available TEXT,
    false_positive_risk TEXT,
    would_have_passed_rules INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""


def get_connection(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or intel_config.LEARNING_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def record_candidate(conn, *, run_date: dt.date, ticker: str, opportunity_score: int,
                      early_signal_score: int, convergence_score: int, alert_level: str,
                      regime: str, categories_hit: list[str], evidence_for: list[str],
                      evidence_against: list[str], trade_id: Optional[str] = None) -> int:
    cur = conn.execute(
        "INSERT INTO candidates (run_date, ticker, opportunity_score, early_signal_score, "
        "convergence_score, alert_level, regime, categories_hit, evidence_for, evidence_against, "
        "trade_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_date.isoformat(), ticker, opportunity_score, early_signal_score, convergence_score,
         alert_level, regime, ",".join(categories_hit), json.dumps(evidence_for),
         json.dumps(evidence_against), trade_id, dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def record_convergence_alert(conn, *, run_date: dt.date, ticker: str, convergence_score: int,
                              categories_hit: list[str], detail: list[str]) -> None:
    conn.execute(
        "INSERT INTO convergence_alerts (run_date, ticker, convergence_score, categories_hit, "
        "detail, created_at) VALUES (?,?,?,?,?,?)",
        (run_date.isoformat(), ticker, convergence_score, ",".join(categories_hit),
         json.dumps(detail), dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()


def record_precatalyst_alert(conn, *, run_date: dt.date, ticker: str, catalyst_event: str,
                              catalyst_date: dt.date, days_until: int, evidence: list[str]) -> None:
    conn.execute(
        "INSERT INTO precatalyst_alerts (run_date, ticker, catalyst_event, catalyst_date, "
        "days_until, evidence, created_at) VALUES (?,?,?,?,?,?,?)",
        (run_date.isoformat(), ticker, catalyst_event, catalyst_date.isoformat(), days_until,
         json.dumps(evidence), dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()


def record_rejected_candidate(conn, *, run_date: dt.date, ticker: str, opportunity_score: int,
                               reason: str) -> None:
    conn.execute(
        "INSERT INTO rejected_candidates (run_date, ticker, opportunity_score, reason, created_at) "
        "VALUES (?,?,?,?,?)",
        (run_date.isoformat(), ticker, opportunity_score, reason,
         dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()


def record_social_verification(conn, *, claim_text: str, ticker: Optional[str], source_platform: str,
                                claim_public_at: Optional[str], classification: str,
                                scanner_would_have_found: Optional[bool], notes: str) -> None:
    conn.execute(
        "INSERT INTO social_verifications (claim_text, ticker, source_platform, claim_public_at, "
        "verified_at, classification, scanner_would_have_found, notes) VALUES (?,?,?,?,?,?,?,?)",
        (claim_text, ticker, source_platform, claim_public_at,
         dt.datetime.now(tz=dt.timezone.utc).isoformat(), classification,
         None if scanner_would_have_found is None else int(scanner_would_have_found), notes),
    )
    conn.commit()


def record_retrospective_test(conn, *, ticker: str, as_of_date: dt.date, would_have_found: str,
                               early_signal_score: int, convergence_score: int, opportunity_score: int,
                               signals_available: list[str], false_positive_risk: str,
                               would_have_passed_rules: bool, notes: str) -> None:
    conn.execute(
        "INSERT INTO retrospective_tests (ticker, as_of_date, would_have_found, early_signal_score, "
        "convergence_score, opportunity_score, signals_available, false_positive_risk, "
        "would_have_passed_rules, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticker, as_of_date.isoformat(), would_have_found, early_signal_score, convergence_score,
         opportunity_score, json.dumps(signals_available), false_positive_risk,
         int(would_have_passed_rules), notes, dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()


# --------------------------- Performance analytics ---------------------------

def _read_closed_trades_from_journal(journal_csv_path: Path) -> list[dict]:
    if not journal_csv_path.exists():
        return []
    with journal_csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["event_type"] == "EXIT"]


def compute_overall_performance(journal_csv_path: Path) -> dict:
    """Win rate / avg win / avg loss / expectancy / profit factor from the
    existing papertrader trade journal. With few or zero trades this
    correctly returns near-empty stats -- that's honest, not broken; the
    whole point of this experiment is that these numbers need dozens of
    real trades before they mean anything."""
    exits = _read_closed_trades_from_journal(journal_csv_path)
    n = len(exits)
    if n == 0:
        return {"num_trades": 0, "note": "No closed trades yet -- statistics not yet meaningful."}

    pnls = [float(r["pnl_dollars"]) for r in exits]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "num_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / n, 2),
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "expectancy": round(sum(pnls) / n, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
    }


def compute_performance_by_alert_level(conn, journal_csv_path: Path) -> dict[str, dict]:
    """Breaks down realized P/L by the alert level that produced each
    trade, via candidates.trade_id -> journal EXIT rows. Same join
    pattern extends to catalyst type / sector / regime / convergence
    combination as more columns are grouped by -- not built out further
    yet since there isn't enough trade history to make those breakdowns
    meaningful (see module docstring)."""
    exits = {r["trade_id"]: float(r["pnl_dollars"]) for r in _read_closed_trades_from_journal(journal_csv_path)}
    if not exits:
        return {}

    rows = conn.execute(
        "SELECT trade_id, alert_level FROM candidates WHERE trade_id IS NOT NULL"
    ).fetchall()

    by_level: dict[str, list[float]] = {}
    for row in rows:
        pnl = exits.get(row["trade_id"])
        if pnl is None:
            continue
        by_level.setdefault(row["alert_level"], []).append(pnl)

    result = {}
    for level, pnls in by_level.items():
        wins = [p for p in pnls if p > 0]
        result[level] = {
            "num_trades": len(pnls),
            "win_rate_pct": round(100 * len(wins) / len(pnls), 2) if pnls else 0.0,
            "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        }
    return result
