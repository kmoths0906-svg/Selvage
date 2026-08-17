"""
Append-only logs. Nothing in this module ever opens a file in a mode that
could overwrite or edit a previous row -- every function here opens in
append mode and writes exactly one new row. That is the mechanism, not
just a policy, behind "never alter, delete, or retroactively optimize
losing trades": the code simply has no path that rewrites history.

A trade produces two rows over its life: an ENTRY row when opened, and an
EXIT row when closed, linked by trade_id. Rejected signals get their own
log so we have an honest record of what we *didn't* trade and why.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Optional

from . import config

TRADE_JOURNAL_FIELDS = [
    "trade_id", "event_type", "timestamp", "ticker", "side",
    "price", "shares", "dollar_amount", "stop_loss", "profit_target",
    "reason_entry", "reason_exit", "pnl_dollars", "pnl_pct",
    "account_balance_after",
]

REJECTED_SIGNALS_FIELDS = ["timestamp", "ticker", "reason", "detail"]

EQUITY_CURVE_FIELDS = ["timestamp", "cash", "positions_value", "equity"]


def _append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def append_trade_entry(
    *,
    trade_id: str,
    timestamp: dt.datetime,
    ticker: str,
    entry_price: float,
    shares: float,
    dollar_amount: float,
    stop_loss: float,
    profit_target: float,
    reason_entry: str,
    account_balance_after: float,
    path: Optional[Path] = None,
) -> None:
    path = path or config.TRADE_JOURNAL_PATH
    _append_row(path, TRADE_JOURNAL_FIELDS, {
        "trade_id": trade_id,
        "event_type": "ENTRY",
        "timestamp": timestamp.isoformat(),
        "ticker": ticker,
        "side": "buy",
        "price": entry_price,
        "shares": shares,
        "dollar_amount": dollar_amount,
        "stop_loss": stop_loss,
        "profit_target": profit_target,
        "reason_entry": reason_entry,
        "reason_exit": "",
        "pnl_dollars": "",
        "pnl_pct": "",
        "account_balance_after": account_balance_after,
    })


def append_trade_exit(
    *,
    trade_id: str,
    timestamp: dt.datetime,
    ticker: str,
    exit_price: float,
    shares: float,
    dollar_amount: float,
    reason_exit: str,
    pnl_dollars: float,
    pnl_pct: float,
    account_balance_after: float,
    path: Optional[Path] = None,
) -> None:
    path = path or config.TRADE_JOURNAL_PATH
    _append_row(path, TRADE_JOURNAL_FIELDS, {
        "trade_id": trade_id,
        "event_type": "EXIT",
        "timestamp": timestamp.isoformat(),
        "ticker": ticker,
        "side": "sell",
        "price": exit_price,
        "shares": shares,
        "dollar_amount": dollar_amount,
        "stop_loss": "",
        "profit_target": "",
        "reason_entry": "",
        "reason_exit": reason_exit,
        "pnl_dollars": pnl_dollars,
        "pnl_pct": pnl_pct,
        "account_balance_after": account_balance_after,
    })


def append_rejected_signal(
    *,
    timestamp: dt.datetime,
    ticker: str,
    reason: str,
    detail: str = "",
    path: Optional[Path] = None,
) -> None:
    path = path or config.REJECTED_SIGNALS_PATH
    _append_row(path, REJECTED_SIGNALS_FIELDS, {
        "timestamp": timestamp.isoformat(),
        "ticker": ticker,
        "reason": reason,
        "detail": detail,
    })


def append_equity_point(
    *,
    timestamp: dt.datetime,
    cash: float,
    positions_value: float,
    equity: float,
    path: Optional[Path] = None,
) -> None:
    path = path or config.EQUITY_CURVE_PATH
    _append_row(path, EQUITY_CURVE_FIELDS, {
        "timestamp": timestamp.isoformat(),
        "cash": cash,
        "positions_value": positions_value,
        "equity": equity,
    })
