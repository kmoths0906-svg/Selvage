from __future__ import annotations

import csv
import datetime as dt

import intel_engine
import learning_db
from intelligence import config as intel_config
from intelligence import macro, sectors
from intelligence.data_providers import (
    Filing, FakeEdgarProvider, FakeOptionsProvider, OptionChain, OptionContract,
)
from papertrader import config as pt_config
from papertrader.data_source import FakeDataProvider
from papertrader.portfolio import Portfolio

from .synth import flat_series, recent_acceleration_series, with_breakout_high, with_volume_spike

END = "2026-08-17"   # last completed session
NOW = dt.datetime(2026, 8, 18, 16, 30, tzinfo=pt_config.TIMEZONE)  # "today" the engine runs


def _all_needed_tickers() -> set[str]:
    return (
        set(intel_config.CANDIDATE_UNIVERSE)
        | set(macro.config.MACRO_TICKERS.values())
        | set(intel_config.SECTOR_ETFS.values())
        | {intel_config.BENCHMARK_TICKER}
    )


def _build_histories(strong_ticker: str) -> dict:
    histories = {t: flat_series(45, END) for t in _all_needed_tickers()}

    # Contained "risk on" nudge to the broad market, VIX easing -- kept to
    # the last 5 sessions so it doesn't distort 20d benchmark returns used
    # for relative-strength comparisons elsewhere.
    for key in ("sp500", "nasdaq100", "russell2000"):
        histories[macro.config.MACRO_TICKERS[key]] = recent_acceleration_series(45, END, 5, 3.0)
    histories[macro.config.MACRO_TICKERS["vix"]] = recent_acceleration_series(45, END, 5, -10.0)

    # The sector the strong ticker lives in, independently strengthening.
    from scoring.convergence import TICKER_SECTOR_MAP
    sector = TICKER_SECTOR_MAP[strong_ticker]
    histories[intel_config.SECTOR_ETFS[sector]] = recent_acceleration_series(45, END, 5, 9.0)

    # The strong ticker itself: fresh breakout + volume spike.
    df = recent_acceleration_series(45, END, 5, 6.0)
    df = with_breakout_high(df, above_pct=8.0)
    df = with_volume_spike(df, multiple=4.0, days=1)
    histories[strong_ticker] = df

    return histories


def _edgar_provider(strong_ticker: str) -> FakeEdgarProvider:
    filing = Filing(
        ticker=strong_ticker, cik="0000000001", form_type="8-K",
        filed_date=NOW.date() - dt.timedelta(days=1), accession_number="0000000001-26-000001",
        primary_doc_url="https://example.invalid/doc.htm", items=("2.02",),
        retrieved_at=dt.datetime.now(tz=dt.timezone.utc),
    )
    return FakeEdgarProvider({strong_ticker: [filing]}, reference_date=NOW.date())


def _options_provider(strong_ticker: str) -> FakeOptionsProvider:
    contract = OptionContract(
        ticker=strong_ticker, expiration="2026-09-19", strike=200.0, contract_type="call",
        last_price=2.0, bid=1.9, ask=2.1, volume=500, open_interest=100, implied_volatility=0.4,
    )
    chain = OptionChain(
        ticker=strong_ticker, expiration="2026-09-19", underlying_price=200.0,
        calls=(contract,), puts=(), retrieved_at=dt.datetime.now(tz=dt.timezone.utc),
    )
    return FakeOptionsProvider({(strong_ticker, "2026-09-19"): chain})


def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(pt_config, "PORTFOLIO_STATE_PATH", tmp_path / "portfolio_state.json")
    monkeypatch.setattr(pt_config, "TRADE_JOURNAL_PATH", tmp_path / "trade_journal.csv")
    monkeypatch.setattr(pt_config, "REJECTED_SIGNALS_PATH", tmp_path / "rejected_signals.csv")
    monkeypatch.setattr(pt_config, "EQUITY_CURVE_PATH", tmp_path / "equity_curve.csv")


def test_full_pipeline_executes_a_trade_when_everything_converges(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    strong_ticker = "AAPL"
    histories = _build_histories(strong_ticker)

    provider = FakeDataProvider(histories, as_of=NOW)
    edgar_provider = _edgar_provider(strong_ticker)
    options_provider = _options_provider(strong_ticker)
    db_conn = learning_db.get_connection(tmp_path / "learning.db")

    result = intel_engine.run_daily_intelligence(
        provider, edgar_provider, options_provider,
        earnings_lookup=lambda t: [], now=NOW, db_conn=db_conn,
    )

    assert strong_ticker in result.portfolio.positions
    assert strong_ticker in result.executed_trade_ids[0] or result.executed_trade_ids

    pos = result.portfolio.positions[strong_ticker]
    dollars_at_risk = (pos.entry_price - pos.stop_loss) * pos.shares
    equity = result.portfolio.equity({strong_ticker: pos.entry_price})
    assert dollars_at_risk <= equity * pt_config.MAX_RISK_PER_TRADE_PCT + 0.05

    with pt_config.TRADE_JOURNAL_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    entry_rows = [r for r in rows if r["event_type"] == "ENTRY" and r["ticker"] == strong_ticker]
    assert len(entry_rows) == 1

    cand_rows = db_conn.execute(
        "SELECT trade_id FROM candidates WHERE ticker=? AND trade_id IS NOT NULL", (strong_ticker,)
    ).fetchall()
    assert len(cand_rows) == 1


def test_pipeline_produces_no_trade_when_nothing_converges(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    # Every ticker flat -- no scanner hits, no catalysts, no options flow.
    histories = {t: flat_series(45, END) for t in _all_needed_tickers()}
    provider = FakeDataProvider(histories, as_of=NOW)
    edgar_provider = FakeEdgarProvider({}, reference_date=NOW.date())
    options_provider = FakeOptionsProvider({})
    db_conn = learning_db.get_connection(tmp_path / "learning.db")

    result = intel_engine.run_daily_intelligence(
        provider, edgar_provider, options_provider,
        earnings_lookup=lambda t: [], now=NOW, db_conn=db_conn,
    )

    assert result.executed_trade_ids == []
    assert result.portfolio.positions == {}
    assert result.portfolio.cash == pt_config.STARTING_CAPITAL


def test_shortlist_funnel_caps_wide_universe_and_always_enriches_core(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)

    # Every ticker flat except: ALL wide-universe tickers get made
    # "notable" (volume spike) so the shortlist cap actually has to bind.
    histories = {t: flat_series(45, END) for t in _all_needed_tickers()}
    for t in intel_config.WIDE_UNIVERSE:
        histories[t] = with_volume_spike(flat_series(45, END), multiple=3.0, days=1)

    provider = FakeDataProvider(histories, as_of=NOW)
    edgar_provider = FakeEdgarProvider({}, reference_date=NOW.date())
    options_provider = FakeOptionsProvider({})
    db_conn = learning_db.get_connection(tmp_path / "learning.db")

    result = intel_engine.run_daily_intelligence(
        provider, edgar_provider, options_provider,
        earnings_lookup=lambda t: [], now=NOW, db_conn=db_conn,
    )

    assert result.universe_size == len(intel_config.CANDIDATE_UNIVERSE)
    # CORE (16) always enriched + at most SHORTLIST_MAX_FROM_WIDE promoted from WIDE.
    assert result.shortlist_size == len(intel_config.CORE_UNIVERSE) + intel_config.SHORTLIST_MAX_FROM_WIDE
    assert len(result.candidates) == result.shortlist_size

    enriched_tickers = {c.ticker for c in result.candidates}
    assert set(intel_config.CORE_UNIVERSE).issubset(enriched_tickers)

    # Every scanned-but-not-enriched wide ticker should have a cheap
    # rejection log entry instead of a full candidate row.
    non_enriched_count = db_conn.execute(
        "SELECT COUNT(*) FROM rejected_candidates WHERE reason NOT LIKE 'No independent%'"
    ).fetchone()[0]
    assert non_enriched_count == len(intel_config.WIDE_UNIVERSE) - intel_config.SHORTLIST_MAX_FROM_WIDE

    candidates_rows = db_conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    assert candidates_rows == result.shortlist_size


def test_core_ticker_always_enriched_even_when_flat(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    # Nothing notable anywhere -- CORE tickers should still be scored
    # (and end up with alert_level NONE), unlike WIDE tickers which are
    # only scored if the scanner flags them.
    histories = {t: flat_series(45, END) for t in _all_needed_tickers()}
    provider = FakeDataProvider(histories, as_of=NOW)
    edgar_provider = FakeEdgarProvider({}, reference_date=NOW.date())
    options_provider = FakeOptionsProvider({})
    db_conn = learning_db.get_connection(tmp_path / "learning.db")

    result = intel_engine.run_daily_intelligence(
        provider, edgar_provider, options_provider,
        earnings_lookup=lambda t: [], now=NOW, db_conn=db_conn,
    )

    enriched_tickers = {c.ticker for c in result.candidates}
    assert set(intel_config.CORE_UNIVERSE) == enriched_tickers  # nothing from WIDE got promoted
    assert result.shortlist_size == len(intel_config.CORE_UNIVERSE)
