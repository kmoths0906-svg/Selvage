"""
Builds the dashboard the user asked for from the portfolio snapshot, the
trade journal, and the equity curve. Read-only: this module never writes
to the journal, it only summarizes it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .data_source import DataUnavailableError, MarketDataProvider
from .portfolio import Portfolio


@dataclass
class ClosedTrade:
    trade_id: str
    ticker: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    shares: float
    dollar_amount: float
    stop_loss: str
    profit_target: str
    reason_entry: str
    reason_exit: str
    pnl_dollars: float
    pnl_pct: float


def _read_csv(path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _closed_trades(journal_rows: list[dict]) -> list[ClosedTrade]:
    entries = {r["trade_id"]: r for r in journal_rows if r["event_type"] == "ENTRY"}
    trades = []
    for r in journal_rows:
        if r["event_type"] != "EXIT":
            continue
        e = entries.get(r["trade_id"])
        if not e:
            continue
        trades.append(ClosedTrade(
            trade_id=r["trade_id"],
            ticker=r["ticker"],
            entry_timestamp=e["timestamp"],
            exit_timestamp=r["timestamp"],
            entry_price=float(e["price"]),
            exit_price=float(r["price"]),
            shares=float(e["shares"]),
            dollar_amount=float(e["dollar_amount"]),
            stop_loss=e["stop_loss"],
            profit_target=e["profit_target"],
            reason_entry=e["reason_entry"],
            reason_exit=r["reason_exit"],
            pnl_dollars=float(r["pnl_dollars"]),
            pnl_pct=float(r["pnl_pct"]),
        ))
    return trades


def _max_drawdown(equity_rows: list[dict]) -> float:
    peak = None
    max_dd = 0.0
    for row in equity_rows:
        eq = float(row["equity"])
        peak = eq if peak is None else max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return max_dd


@dataclass
class Report:
    starting_balance: float
    current_balance: float
    cash: float
    positions_value: float
    open_positions: list[dict]
    realized_pnl: float
    unrealized_pnl: float
    total_return_pct: float
    num_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    max_drawdown_pct: float
    closed_trades: list[ClosedTrade]
    rejected_signals: list[dict]
    price_data_stale: bool = False


def generate_report(provider: Optional[MarketDataProvider] = None) -> Report:
    portfolio = Portfolio.load()
    journal_rows = _read_csv(config.TRADE_JOURNAL_PATH)
    rejected_rows = _read_csv(config.REJECTED_SIGNALS_PATH)
    equity_rows = _read_csv(config.EQUITY_CURVE_PATH)

    mark_prices: dict[str, float] = {}
    stale = False
    if provider is not None:
        for ticker in portfolio.positions:
            try:
                mark_prices[ticker] = provider.get_latest_price(ticker).price
            except DataUnavailableError:
                stale = True
    else:
        stale = bool(portfolio.positions)

    open_positions = []
    unrealized_pnl = 0.0
    positions_value = 0.0
    for ticker, pos in portfolio.positions.items():
        price = mark_prices.get(ticker, pos.entry_price)
        mv = pos.market_value(price)
        upnl = pos.unrealized_pnl(price)
        positions_value += mv
        unrealized_pnl += upnl
        open_positions.append({
            "ticker": ticker,
            "shares": pos.shares,
            "entry_price": pos.entry_price,
            "current_price": price,
            "stop_loss": pos.stop_loss,
            "profit_target": pos.profit_target,
            "market_value": round(mv, 2),
            "unrealized_pnl": round(upnl, 2),
        })

    current_balance = round(portfolio.cash + positions_value, 2)
    closed = _closed_trades(journal_rows)
    wins = sum(1 for t in closed if t.pnl_dollars > 0)
    losses = sum(1 for t in closed if t.pnl_dollars <= 0)
    win_rate = round(100 * wins / len(closed), 2) if closed else 0.0
    total_return_pct = round(
        100 * (current_balance - portfolio.starting_capital) / portfolio.starting_capital, 4
    )

    return Report(
        starting_balance=portfolio.starting_capital,
        current_balance=current_balance,
        cash=round(portfolio.cash, 2),
        positions_value=round(positions_value, 2),
        open_positions=open_positions,
        realized_pnl=round(portfolio.realized_pnl, 2),
        unrealized_pnl=round(unrealized_pnl, 2),
        total_return_pct=total_return_pct,
        num_trades=len(closed),
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate,
        max_drawdown_pct=round(_max_drawdown(equity_rows) * 100, 2),
        closed_trades=closed,
        rejected_signals=rejected_rows[-20:],
        price_data_stale=stale,
    )


def format_report(r: Report) -> str:
    lines = []
    add = lines.append
    add("=" * 60)
    add("PAPER TRADING DASHBOARD")
    add("=" * 60)
    if r.price_data_stale:
        add("(!) Live prices unavailable — unrealized P/L uses entry price as a placeholder.")
    add(f"Starting balance : ${r.starting_balance:,.2f}")
    add(f"Current balance  : ${r.current_balance:,.2f}")
    add(f"  Cash           : ${r.cash:,.2f}")
    add(f"  Positions      : ${r.positions_value:,.2f}")
    add(f"Realized P/L     : ${r.realized_pnl:,.2f}")
    add(f"Unrealized P/L   : ${r.unrealized_pnl:,.2f}")
    add(f"Total return     : {r.total_return_pct:+.2f}%")
    add(f"Number of trades : {r.num_trades}")
    add(f"Wins / Losses    : {r.wins} / {r.losses}")
    add(f"Win rate         : {r.win_rate_pct:.2f}%")
    add(f"Max drawdown     : {r.max_drawdown_pct:.2f}%")
    add("")

    if r.open_positions:
        add("-- Open positions --")
        for p in r.open_positions:
            add(
                f"  {p['ticker']}: {p['shares']:.4f} sh @ ${p['entry_price']:.2f} "
                f"(now ${p['current_price']:.2f}) | stop ${p['stop_loss']:.2f} "
                f"target ${p['profit_target']:.2f} | unrealized ${p['unrealized_pnl']:+.2f}"
            )
        add("")

    if r.closed_trades:
        add("-- Trade history (plain-English reasoning) --")
        for t in r.closed_trades:
            add(f"  [{t.trade_id}] {t.ticker}  P/L ${t.pnl_dollars:+.2f} ({t.pnl_pct:+.2f}%)")
            add(f"    Entered {t.entry_timestamp} @ ${t.entry_price:.2f} for {t.shares:.4f} shares "
                f"(${t.dollar_amount:.2f}); stop ${t.stop_loss}, target ${t.profit_target}")
            add(f"    Why entered: {t.reason_entry}")
            add(f"    Exited {t.exit_timestamp} @ ${t.exit_price:.2f}")
            add(f"    Why exited: {t.reason_exit}")
            add("")

    if r.rejected_signals:
        add("-- Recently rejected signals --")
        for s in r.rejected_signals:
            add(f"  {s['timestamp']}  {s['ticker']}: {s['reason']} ({s['detail']})")

    return "\n".join(lines)
