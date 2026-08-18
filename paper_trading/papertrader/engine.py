"""
Daily orchestration. Run once per trading day:

  1. Mark existing positions to the current live price.
  2. Check each open position for stop-loss / profit-target / max-hold exit.
  3. If there's room for a new position, scan the universe for a signal,
     size it under the 2% risk rule, and execute.
  4. Log everything (fills, rejections, the day's equity) and persist
     account state.

Every price used for a *decision* (entry/exit trigger, sizing) comes from
`MarketDataProvider.get_latest_price` (the real quote as of right now) or
from `get_completed_daily_bars` (sessions that have already closed).
Nothing here can see tomorrow.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from . import broker_sim, config, journal, risk, strategy
from .data_source import DataUnavailableError, MarketDataProvider
from .portfolio import Portfolio, Position

log = logging.getLogger(__name__)


def _days_held(provider: MarketDataProvider, ticker: str, entry_bar_date: str) -> int:
    try:
        bars = provider.get_completed_daily_bars(ticker, lookback_days=config.MAX_HOLD_DAYS + 15)
    except DataUnavailableError:
        return 0
    entry_ts = pd.Timestamp(entry_bar_date)
    return int((bars.index > entry_ts).sum())


def check_exits(provider: MarketDataProvider, portfolio: Portfolio, now: dt.datetime) -> dict[str, float]:
    """Mark open positions to the current live price and close any that
    hit their stop, target, or max-hold period. Mutates `portfolio` and
    the trade journal in place; returns the mark_prices dict built along
    the way so callers don't have to re-fetch quotes they already paid
    for. Split out of run() so other callers (e.g. the intelligence
    engine) can check exits without duplicating this logic."""
    mark_prices: dict[str, float] = {}
    for ticker in list(portfolio.positions.keys()):
        try:
            quote = provider.get_latest_price(ticker)
            mark_prices[ticker] = quote.price
        except DataUnavailableError as e:
            log.warning("No live quote for held position %s: %s", ticker, e)

    for ticker, pos in list(portfolio.positions.items()):
        price = mark_prices.get(ticker)
        if price is None:
            continue

        exit_reason = None
        if price <= pos.stop_loss:
            exit_reason = f"Stop-loss hit: price {price:.4f} <= stop {pos.stop_loss:.4f}"
        elif price >= pos.profit_target:
            exit_reason = f"Profit target hit: price {price:.4f} >= target {pos.profit_target:.4f}"
        else:
            held = _days_held(provider, ticker, pos.entry_bar_date)
            if held >= config.MAX_HOLD_DAYS:
                exit_reason = (
                    f"Max hold period reached ({held} trading days >= "
                    f"{config.MAX_HOLD_DAYS}) without hitting stop or target"
                )

        if exit_reason is None:
            continue

        fill = broker_sim.simulate_sell_fill(price)
        proceeds = round(fill.fill_price * pos.shares - fill.commission, 2)
        pnl_dollars = round(
            (fill.fill_price - pos.entry_price) * pos.shares - pos.entry_commission - fill.commission, 2
        )
        cost_basis = pos.entry_price * pos.shares
        pnl_pct = round((pnl_dollars / cost_basis) * 100, 4) if cost_basis else 0.0

        portfolio.close_position(ticker, proceeds, pnl_dollars)
        mark_prices.pop(ticker, None)

        journal.append_trade_exit(
            trade_id=pos.trade_id,
            timestamp=now,
            ticker=ticker,
            exit_price=fill.fill_price,
            shares=pos.shares,
            dollar_amount=proceeds,
            reason_exit=exit_reason,
            pnl_dollars=pnl_dollars,
            pnl_pct=pnl_pct,
            account_balance_after=round(portfolio.equity(mark_prices), 2),
        )
        log.info("EXIT %s: %s | pnl=$%.2f (%.2f%%)", ticker, exit_reason, pnl_dollars, pnl_pct)

    return mark_prices


def run(provider: MarketDataProvider, *, force: bool = False, now: dt.datetime | None = None) -> Portfolio:
    now = now or dt.datetime.now(tz=config.TIMEZONE)
    today_str = now.date().isoformat()

    portfolio = Portfolio.load()

    if portfolio.last_run_date == today_str and not force:
        log.info("Already ran today (%s); skipping. Pass force=True to override.", today_str)
        return portfolio

    # --- 1. Check exits on existing positions ---------------------------
    mark_prices = check_exits(provider, portfolio, now)

    # --- 2. Look for a new entry if we have room -------------------------
    open_slots = config.MAX_OPEN_POSITIONS - len(portfolio.positions)
    if open_slots > 0:
        for ticker in config.UNIVERSE:
            if len(portfolio.positions) >= config.MAX_OPEN_POSITIONS:
                break
            if ticker in portfolio.positions:
                continue

            try:
                bars = provider.get_completed_daily_bars(
                    ticker, lookback_days=config.MIN_BARS_REQUIRED + 30
                )
            except DataUnavailableError as e:
                journal.append_rejected_signal(
                    timestamp=now, ticker=ticker, reason="data_unavailable", detail=str(e)
                )
                continue

            signal, rejection = strategy.evaluate(ticker, bars, now)
            if rejection is not None:
                journal.append_rejected_signal(
                    timestamp=now, ticker=ticker, reason=rejection.reason, detail=rejection.detail
                )
                continue

            try:
                quote = provider.get_latest_price(ticker)
            except DataUnavailableError as e:
                journal.append_rejected_signal(
                    timestamp=now, ticker=ticker, reason="no_live_quote", detail=str(e)
                )
                continue

            fill = broker_sim.simulate_buy_fill(quote.price)
            risk_per_share = signal.reference_close - signal.planned_stop
            actual_stop = round(fill.fill_price - risk_per_share, 4)
            actual_target = round(fill.fill_price + config.REWARD_RISK_RATIO * risk_per_share, 4)

            equity_now = portfolio.equity(mark_prices)
            sizing = risk.size_position(equity_now, portfolio.cash, fill.fill_price, actual_stop)
            if not sizing.accepted:
                journal.append_rejected_signal(
                    timestamp=now, ticker=ticker, reason="sizing_rejected",
                    detail=sizing.rejected_reason or "",
                )
                continue

            cost = round(sizing.shares * fill.fill_price + fill.commission, 2)
            trade_id = portfolio.next_trade_id()
            pos = Position(
                trade_id=trade_id,
                ticker=ticker,
                shares=sizing.shares,
                entry_price=fill.fill_price,
                stop_loss=actual_stop,
                profit_target=actual_target,
                entry_bar_date=str(signal.signal_date.date()),
                entry_timestamp=now.isoformat(),
                entry_reason=signal.reason,
                dollars_at_risk=sizing.dollars_at_risk,
                entry_commission=fill.commission,
            )
            portfolio.open_position(pos, cost)
            mark_prices[ticker] = quote.price

            journal.append_trade_entry(
                trade_id=trade_id,
                timestamp=now,
                ticker=ticker,
                entry_price=fill.fill_price,
                shares=sizing.shares,
                dollar_amount=cost,
                stop_loss=actual_stop,
                profit_target=actual_target,
                reason_entry=signal.reason,
                account_balance_after=round(portfolio.equity(mark_prices), 2),
            )
            log.info(
                "ENTRY %s: %.6f shares @ %.4f (stop %.4f, target %.4f, risking $%.2f)",
                ticker, sizing.shares, fill.fill_price, actual_stop, actual_target, sizing.dollars_at_risk,
            )

    # --- 3. Record equity curve point + persist --------------------------
    positions_value = sum(
        pos.market_value(mark_prices.get(t, pos.entry_price)) for t, pos in portfolio.positions.items()
    )
    equity = round(portfolio.cash + positions_value, 2)
    journal.append_equity_point(
        timestamp=now, cash=round(portfolio.cash, 2), positions_value=round(positions_value, 2), equity=equity
    )

    portfolio.last_run_date = today_str
    portfolio.save()
    return portfolio
