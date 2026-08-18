"""
Intelligence engine: the daily orchestrator that ties every module
together and is the ONLY place a scored candidate can become an actual
paper trade. It does that by calling papertrader's own, already-tested
risk/broker_sim/portfolio/journal code -- not a reimplementation.

Order of operations, once per day:
  1. Check exits on existing positions (papertrader.engine.check_exits,
     reused as-is).
  2. Compute macro regime + cross-asset chains.
  3. Rank sector rotation.
  4. Run the daily scanner over the candidate universe.
  5. Pull SEC EDGAR catalysts (recent past) + earnings dates + the hand
     maintained macro seed -> the 14-day forward calendar.
  6. Pull options snapshots (free-tier, see intelligence/options_lite.py).
  7. Cross-reference the calendar against today's activity
     (pre-positioning).
  8. Score every candidate: early-signal, convergence, opportunity.
  9. Record everything to the learning database.
  10. Execute any 🔴 ACTIONABLE setup that still has room in the
      portfolio and is long-only (bullish evidence required -- this
      system never shorts).
  11. Record the day's equity point and persist portfolio state.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import learning_db
from catalysts import calendar as calendar_mod
from catalysts import pre_positioning
from catalysts.models import Catalyst
from intelligence import config as intel_config
from intelligence import edgar as edgar_mod
from intelligence import macro, scanner, sectors
from intelligence import options_lite
from intelligence.data_providers import EdgarProvider, OptionsDataProvider
from intelligence.macro import ChainResult, RegimeResult
from intelligence.scanner import ScanResult
from intelligence.sectors import SectorStrength
from intelligence.options_lite import OptionsSnapshotResult
from papertrader import broker_sim, config as pt_config, engine as pt_engine, journal, risk
from papertrader.data_source import DataUnavailableError, MarketDataProvider
from papertrader.portfolio import Portfolio, Position
from scoring import convergence, early_signal, opportunity
from scoring.convergence import ConvergenceResult
from scoring.early_signal import EarlySignalResult
from scoring.opportunity import OpportunityResult


@dataclass
class CandidateResult:
    ticker: str
    scan: ScanResult
    early_signal: EarlySignalResult
    convergence: ConvergenceResult
    opportunity: OpportunityResult
    options: Optional[OptionsSnapshotResult]
    trade_id: Optional[str] = None


@dataclass
class IntelRunResult:
    run_date: dt.date
    generated_at: dt.datetime
    regime: RegimeResult
    chains: list[ChainResult]
    sector_ranking: list[SectorStrength]
    strengthening_sectors: list[SectorStrength]
    calendar: list[Catalyst]
    today_catalysts: list[Catalyst]
    precatalyst_alerts: list
    candidates: list[CandidateResult]
    convergence_alert_candidates: list[CandidateResult]
    executed_trade_ids: list[str]
    noise_ignored: list[str]
    portfolio: Portfolio


def _atr14(bars: pd.DataFrame) -> Optional[float]:
    if len(bars) < 15:
        return None
    prev_close = bars["Close"].shift(1)
    tr = pd.concat(
        [bars["High"] - bars["Low"], (bars["High"] - prev_close).abs(), (bars["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    val = tr.rolling(14).mean().iloc[-1]
    return float(val) if val == val else None  # NaN check


def _build_entry_reason(cand: CandidateResult) -> str:
    parts = [
        f"Opportunity {cand.opportunity.score}/100, Convergence {cand.convergence.score}/100 "
        f"({', '.join(cand.convergence.categories_hit)}), Early-signal {cand.early_signal.score}/100 "
        f"({cand.early_signal.label}).",
    ]
    if cand.opportunity.evidence_for:
        parts.append("Evidence for: " + "; ".join(cand.opportunity.evidence_for))
    if cand.opportunity.evidence_against:
        parts.append("Evidence against: " + "; ".join(cand.opportunity.evidence_against))
    parts.append(
        f"Holding period: up to {pt_config.MAX_HOLD_DAYS} trading days (time-stop) unless stop/target hit sooner. "
        f"Single target only -- no partial-scaling exits in this version."
    )
    return " | ".join(parts)


def _execute_trade(
    provider: MarketDataProvider, portfolio: Portfolio, cand: CandidateResult,
    now: dt.datetime, mark_prices: dict[str, float],
) -> Optional[str]:
    ticker = cand.ticker
    try:
        bars = provider.get_completed_daily_bars(ticker, 40)
        quote = provider.get_latest_price(ticker)
    except DataUnavailableError as e:
        journal.append_rejected_signal(timestamp=now, ticker=ticker, reason="data_unavailable", detail=str(e))
        return None

    atr = _atr14(bars)
    if atr is None or atr <= 0:
        journal.append_rejected_signal(timestamp=now, ticker=ticker, reason="invalid_atr", detail=str(atr))
        return None

    fill = broker_sim.simulate_buy_fill(quote.price)
    stop = round(fill.fill_price - pt_config.STOP_ATR_MULT * atr, 4)
    target = round(fill.fill_price + pt_config.REWARD_RISK_RATIO * (fill.fill_price - stop), 4)

    equity_now = portfolio.equity(mark_prices)
    sizing = risk.size_position(equity_now, portfolio.cash, fill.fill_price, stop)
    if not sizing.accepted:
        journal.append_rejected_signal(
            timestamp=now, ticker=ticker, reason="sizing_rejected", detail=sizing.rejected_reason or ""
        )
        return None

    cost = round(sizing.shares * fill.fill_price + fill.commission, 2)
    trade_id = portfolio.next_trade_id()
    reason = _build_entry_reason(cand)

    pos = Position(
        trade_id=trade_id, ticker=ticker, shares=sizing.shares, entry_price=fill.fill_price,
        stop_loss=stop, profit_target=target, entry_bar_date=str(bars.index[-1].date()),
        entry_timestamp=now.isoformat(), entry_reason=reason, dollars_at_risk=sizing.dollars_at_risk,
        entry_commission=fill.commission,
    )
    portfolio.open_position(pos, cost)
    mark_prices[ticker] = quote.price

    journal.append_trade_entry(
        trade_id=trade_id, timestamp=now, ticker=ticker, entry_price=fill.fill_price,
        shares=sizing.shares, dollar_amount=cost, stop_loss=stop, profit_target=target,
        reason_entry=reason, account_balance_after=round(portfolio.equity(mark_prices), 2),
    )
    return trade_id


def run_daily_intelligence(
    provider: MarketDataProvider,
    edgar_provider: EdgarProvider,
    options_provider: OptionsDataProvider,
    *,
    earnings_lookup: calendar_mod.EarningsLookup = calendar_mod.yfinance_earnings_lookup,
    now: Optional[dt.datetime] = None,
    db_conn=None,
) -> IntelRunResult:
    now = now or dt.datetime.now(tz=pt_config.TIMEZONE)
    today = now.date()
    db_conn = db_conn or learning_db.get_connection()

    portfolio = Portfolio.load()

    # 1. Exits on existing positions -- reuse papertrader's tested logic.
    mark_prices = pt_engine.check_exits(provider, portfolio, now)

    # 2. Macro regime + cross-asset chains.
    macro_metrics = macro.fetch_macro_metrics(provider)
    regime = macro.classify_regime(macro_metrics, now)
    chains = macro.check_cross_asset_chains(macro_metrics)

    # 3. Sector rotation.
    sector_ranking = sectors.rank_sectors(provider)
    strengthening = sectors.strengthening_sectors(sector_ranking)

    # 4. Daily scanner.
    scan_results = scanner.scan_universe(provider, intel_config.CANDIDATE_UNIVERSE)
    scan_by_ticker = {s.ticker: s for s in scan_results}

    # 5. Catalysts: EDGAR (recent past, for scoring) + earnings + macro seed (forward calendar).
    edgar_catalysts = edgar_mod.build_edgar_catalysts(edgar_provider, intel_config.CANDIDATE_UNIVERSE)
    earnings_catalysts = calendar_mod.build_earnings_catalysts(intel_config.CANDIDATE_UNIVERSE, earnings_lookup)
    cal = calendar_mod.build_calendar(edgar_catalysts, earnings_catalysts, today=today)
    today_cats = calendar_mod.today_catalysts(cal, today=today)

    # 6. Options snapshots.
    options_results = options_lite.scan_universe_options(options_provider, intel_config.CANDIDATE_UNIVERSE)
    options_by_ticker = {o.ticker: o for o in options_results}

    # 7. Pre-positioning cross-reference.
    precatalyst_alerts = pre_positioning.detect_pre_catalyst_activity(cal, scan_results, options_results, today=today)
    for a in precatalyst_alerts:
        learning_db.record_precatalyst_alert(
            db_conn, run_date=today, ticker=a.ticker, catalyst_event=a.catalyst.event,
            catalyst_date=a.catalyst.date, days_until=a.days_until_catalyst, evidence=a.evidence,
        )

    # 8-9. Score every candidate and record it.
    candidates: list[CandidateResult] = []
    noise_ignored: list[str] = []
    for ticker in intel_config.CANDIDATE_UNIVERSE:
        scan = scan_by_ticker[ticker]
        ticker_edgar = [c for c in edgar_catalysts if ticker in c.tickers]
        opts = options_by_ticker.get(ticker)

        es = early_signal.score_early_signal(scan, ticker_edgar, opts, today=today)
        conv = convergence.score_convergence(ticker, scan, ticker_edgar, opts, strengthening, regime, today=today)
        opp = opportunity.score_opportunity(scan, ticker_edgar, es, conv, today=today)

        cand = CandidateResult(ticker, scan, es, conv, opp, opts)
        candidates.append(cand)

        learning_db.record_candidate(
            db_conn, run_date=today, ticker=ticker, opportunity_score=opp.score,
            early_signal_score=es.score, convergence_score=conv.score, alert_level=opp.alert_level,
            regime=regime.regime, categories_hit=conv.categories_hit,
            evidence_for=opp.evidence_for, evidence_against=opp.evidence_against,
        )

        if conv.is_alert:
            learning_db.record_convergence_alert(
                db_conn, run_date=today, ticker=ticker, convergence_score=conv.score,
                categories_hit=conv.categories_hit, detail=conv.detail,
            )

        if opp.alert_level == "NONE":
            learning_db.record_rejected_candidate(
                db_conn, run_date=today, ticker=ticker, opportunity_score=opp.score,
                reason="No independent evidence categories converged",
            )
            if es.label == "LIKELY_LATE" and scan.rel_volume and scan.rel_volume >= intel_config.REL_VOLUME_HIGH:
                noise_ignored.append(
                    f"{ticker}: high relative volume ({scan.rel_volume:.1f}x) but already up "
                    f"{scan.ret_20d_pct:+.1f}% over 20d and no converging evidence -- likely already obvious."
                )

    candidates.sort(key=lambda c: c.opportunity.score, reverse=True)
    convergence_alert_candidates = [c for c in candidates if c.convergence.is_alert]

    # 10. Execute actionable setups (long-only, room permitting).
    executed_trade_ids: list[str] = []
    for cand in candidates:
        if cand.opportunity.alert_level != intel_config.ALERT_ACTIONABLE:
            continue
        if cand.ticker in portfolio.positions:
            continue
        if len(portfolio.positions) >= pt_config.MAX_OPEN_POSITIONS:
            break
        bullish = bool(cand.scan.range_breakout) or bool(
            cand.scan.price_accelerating and (cand.scan.ret_3d_pct or 0) > 0
        )
        if not bullish:
            continue  # long-only: no short-selling, so a bearish setup can't be traded here

        trade_id = _execute_trade(provider, portfolio, cand, now, mark_prices)
        if trade_id:
            executed_trade_ids.append(trade_id)
            cand.trade_id = trade_id
            db_conn.execute(
                "UPDATE candidates SET trade_id=? WHERE run_date=? AND ticker=? AND trade_id IS NULL",
                (trade_id, today.isoformat(), cand.ticker),
            )
            db_conn.commit()

    # 11. Equity curve + persist (mirrors papertrader.engine.run's tail).
    positions_value = sum(
        pos.market_value(mark_prices.get(t, pos.entry_price)) for t, pos in portfolio.positions.items()
    )
    equity = round(portfolio.cash + positions_value, 2)
    journal.append_equity_point(
        timestamp=now, cash=round(portfolio.cash, 2), positions_value=round(positions_value, 2), equity=equity,
    )
    portfolio.last_run_date = today.isoformat()
    portfolio.save()

    return IntelRunResult(
        run_date=today, generated_at=now, regime=regime, chains=chains,
        sector_ranking=sector_ranking, strengthening_sectors=strengthening,
        calendar=cal, today_catalysts=today_cats, precatalyst_alerts=precatalyst_alerts,
        candidates=candidates, convergence_alert_candidates=convergence_alert_candidates,
        executed_trade_ids=executed_trade_ids, noise_ignored=noise_ignored, portfolio=portfolio,
    )
