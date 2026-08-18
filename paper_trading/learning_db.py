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

-- See intelligence/universe_validation.py for the state machine this
-- backs. One row per ticker ever seen in CANDIDATE_UNIVERSE.
CREATE TABLE IF NOT EXISTS ticker_validation (
    ticker TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    last_checked_date TEXT,
    last_success_date TEXT,
    last_price REAL,
    last_volume INTEGER,
    last_error TEXT,
    quarantined_at TEXT,
    quarantine_reason TEXT,
    replacement_ticker TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

-- One row per ticker per run that passed through the shortlist funnel
-- (intel_engine.py) -- CORE_UNIVERSE tickers (always promoted, not
-- ranked) and every WIDE_UNIVERSE ticker the scanner flagged notable
-- (ranked by quick_score, whether or not the cap let it through). This
-- is what makes the funnel auditable after the fact: without it, the
-- pre-cap ranking only ever existed in memory during the run and was
-- lost the moment the process exited.
CREATE TABLE IF NOT EXISTS shortlist_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    tier TEXT NOT NULL,          -- 'CORE' or 'WIDE'
    quick_score REAL,             -- NULL for CORE (not ranked by quick_score)
    rank INTEGER,                 -- rank among WIDE notable tickers, 1 = highest; NULL for CORE
    promoted INTEGER NOT NULL,    -- 1 if enriched this run, 0 if excluded by the shortlist cap
    created_at TEXT NOT NULL
);
"""


# ticker_validation.status values. Defined here (the shared data layer,
# already a dependency of everything) rather than in
# intelligence/universe_validation.py, so the two modules don't form an
# import cycle -- universe_validation.py imports these from here.
STATUS_ACTIVE = "ACTIVE"
STATUS_TEMPORARY_DATA_FAILURE = "TEMPORARY_DATA_FAILURE"
STATUS_STALE = "STALE"
STATUS_POSSIBLY_DELISTED = "POSSIBLY_DELISTED"
STATUS_RENAMED_MERGED = "RENAMED_MERGED"
STATUS_QUARANTINED = "QUARANTINED"


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


# --------------------------- Ticker validation ---------------------------
# Raw accessors only -- the state-machine logic (when a status changes,
# what counts as a failure, quarantine thresholds) lives in
# intelligence/universe_validation.py, which calls these.

def get_validation_row(conn, ticker: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM ticker_validation WHERE ticker=?", (ticker,)).fetchone()


def upsert_validation(
    conn, *, ticker: str, status: str, consecutive_failures: int, consecutive_successes: int,
    last_checked_date: dt.date, last_success_date: Optional[dt.date] = None,
    last_price: Optional[float] = None, last_volume: Optional[int] = None,
    last_error: Optional[str] = None, quarantined_at: Optional[dt.date] = None,
    quarantine_reason: Optional[str] = None, replacement_ticker: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    now = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO ticker_validation
            (ticker, status, consecutive_failures, consecutive_successes, last_checked_date,
             last_success_date, last_price, last_volume, last_error, quarantined_at,
             quarantine_reason, replacement_ticker, notes, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
            status=excluded.status,
            consecutive_failures=excluded.consecutive_failures,
            consecutive_successes=excluded.consecutive_successes,
            last_checked_date=excluded.last_checked_date,
            last_success_date=COALESCE(excluded.last_success_date, ticker_validation.last_success_date),
            last_price=COALESCE(excluded.last_price, ticker_validation.last_price),
            last_volume=COALESCE(excluded.last_volume, ticker_validation.last_volume),
            last_error=excluded.last_error,
            quarantined_at=COALESCE(excluded.quarantined_at, ticker_validation.quarantined_at),
            quarantine_reason=COALESCE(excluded.quarantine_reason, ticker_validation.quarantine_reason),
            replacement_ticker=COALESCE(excluded.replacement_ticker, ticker_validation.replacement_ticker),
            notes=COALESCE(excluded.notes, ticker_validation.notes),
            updated_at=excluded.updated_at
        """,
        (
            ticker, status, consecutive_failures, consecutive_successes, last_checked_date.isoformat(),
            last_success_date.isoformat() if last_success_date else None, last_price, last_volume,
            last_error, quarantined_at.isoformat() if quarantined_at else None, quarantine_reason,
            replacement_ticker, notes, now,
        ),
    )
    conn.commit()


def get_tickers_by_status(conn, status: str) -> list[str]:
    rows = conn.execute("SELECT ticker FROM ticker_validation WHERE status=?", (status,)).fetchall()
    return [r["ticker"] for r in rows]


def get_validation_summary(conn) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) as n FROM ticker_validation GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


# --------------------------- Shortlist funnel audit ---------------------------

def record_shortlist_audit(
    conn, *, run_date: dt.date, ticker: str, tier: str,
    quick_score: Optional[float], rank: Optional[int], promoted: bool,
) -> None:
    conn.execute(
        "INSERT INTO shortlist_audit (run_date, ticker, tier, quick_score, rank, promoted, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_date.isoformat(), ticker, tier, quick_score, rank, int(promoted),
         dt.datetime.now(tz=dt.timezone.utc).isoformat()),
    )
    conn.commit()


def get_shortlist_audit(conn, run_date: dt.date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM shortlist_audit WHERE run_date=? "
        "ORDER BY tier ASC, promoted DESC, rank ASC",
        (run_date.isoformat(),),
    ).fetchall()
