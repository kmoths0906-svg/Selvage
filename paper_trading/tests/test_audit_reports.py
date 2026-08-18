"""
Tests for the read-only audit report functions (items 2-4 tooling):
format_scan_failures, format_funnel_audit, format_candidate_detail.
All read an existing learning_db connection and must never mutate it.
"""

from __future__ import annotations

import datetime as dt
import json

import learning_db
from intel_report import format_candidate_detail, format_funnel_audit, format_scan_failures

DATE = dt.date(2026, 8, 19)


def _conn(tmp_path):
    return learning_db.get_connection(tmp_path / "learning.db")


def test_show_failures_empty_db_reports_none_not_a_crash(tmp_path):
    conn = _conn(tmp_path)
    out = format_scan_failures(conn, DATE)
    assert "No non-ACTIVE tickers" in out


def test_show_failures_lists_non_active_tickers_with_raw_error(tmp_path):
    conn = _conn(tmp_path)
    learning_db.upsert_validation(
        conn, ticker="XYZ", status=learning_db.STATUS_TEMPORARY_DATA_FAILURE,
        consecutive_failures=1, consecutive_successes=0, last_checked_date=DATE,
        last_error="No daily bars returned for 'XYZ'",
    )
    learning_db.upsert_validation(
        conn, ticker="ABC", status=learning_db.STATUS_ACTIVE,
        consecutive_failures=0, consecutive_successes=1, last_checked_date=DATE,
    )
    out = format_scan_failures(conn, DATE)
    assert "XYZ" in out
    assert "No daily bars returned for 'XYZ'" in out
    assert "ABC" not in out  # ACTIVE ticker correctly excluded
    assert "1 ticker(s)" in out


def test_show_failures_does_not_mutate_db(tmp_path):
    conn = _conn(tmp_path)
    learning_db.upsert_validation(
        conn, ticker="XYZ", status=learning_db.STATUS_TEMPORARY_DATA_FAILURE,
        consecutive_failures=1, consecutive_successes=0, last_checked_date=DATE,
        last_error="boom",
    )
    before = conn.execute("SELECT COUNT(*) FROM ticker_validation").fetchone()[0]
    format_scan_failures(conn, DATE)
    after = conn.execute("SELECT COUNT(*) FROM ticker_validation").fetchone()[0]
    assert before == after == 1


def test_show_funnel_empty_reports_none_not_a_crash(tmp_path):
    conn = _conn(tmp_path)
    out = format_funnel_audit(conn, DATE)
    assert "No shortlist_audit rows" in out


def test_show_funnel_splits_promoted_and_excluded_with_gap(tmp_path):
    conn = _conn(tmp_path)
    learning_db.record_shortlist_audit(
        conn, run_date=DATE, ticker="CORE1", tier="CORE", quick_score=None, rank=None, promoted=True,
    )
    learning_db.record_shortlist_audit(
        conn, run_date=DATE, ticker="WIDE_TOP", tier="WIDE", quick_score=80.0, rank=1, promoted=True,
    )
    learning_db.record_shortlist_audit(
        conn, run_date=DATE, ticker="WIDE_EXCLUDED", tier="WIDE", quick_score=20.0, rank=2, promoted=False,
    )
    out = format_funnel_audit(conn, DATE)
    assert "CORE1" in out
    assert "WIDE_TOP" in out
    assert "WIDE_EXCLUDED" in out
    assert "Promoted" in out and "Excluded by cap" in out
    assert "80.0 - 20.0 = 60.0" in out


def test_show_funnel_notes_when_cap_not_reached(tmp_path):
    conn = _conn(tmp_path)
    learning_db.record_shortlist_audit(
        conn, run_date=DATE, ticker="WIDE_ONLY", tier="WIDE", quick_score=50.0, rank=1, promoted=True,
    )
    out = format_funnel_audit(conn, DATE)
    assert "Cap not reached" in out


def test_show_candidate_missing_row_reports_none_not_a_crash(tmp_path):
    conn = _conn(tmp_path)
    out = format_candidate_detail(conn, DATE, ["NOPE"])
    assert "No candidate row for NOPE" in out


def test_show_candidate_shows_scores_and_evidence(tmp_path):
    conn = _conn(tmp_path)
    learning_db.record_candidate(
        conn, run_date=DATE, ticker="AAPL", opportunity_score=66, early_signal_score=55,
        convergence_score=77, alert_level="HIGH_CONVICTION_WATCH", regime="RISK_ON",
        categories_hit=["CATALYST", "SECTOR_STRENGTH"],
        evidence_for=["8-K filed", "Technology outperforming SPY"],
        evidence_against=["No options flow"],
    )
    out = format_candidate_detail(conn, DATE, ["AAPL"])
    assert "Opportunity 66" in out
    assert "Convergence 77" in out
    assert "HIGH_CONVICTION_WATCH" in out
    assert "CATALYST" in out and "SECTOR_STRENGTH" in out
    assert "8-K filed" in out
    assert "No options flow" in out


def test_show_candidate_handles_multiple_tickers_in_one_call(tmp_path):
    conn = _conn(tmp_path)
    for t, opp in [("AAPL", 66), ("PFE", 66), ("SCHW", 65)]:
        learning_db.record_candidate(
            conn, run_date=DATE, ticker=t, opportunity_score=opp, early_signal_score=50,
            convergence_score=59, alert_level="DEVELOPING", regime="MIXED_UNCLEAR",
            categories_hit=["PRICE_VOLUME"], evidence_for=["evidence"], evidence_against=[],
        )
    out = format_candidate_detail(conn, DATE, ["AAPL", "PFE", "SCHW"])
    assert "AAPL" in out and "PFE" in out and "SCHW" in out
