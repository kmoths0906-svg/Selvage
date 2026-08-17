"""
Account state: cash, open positions, realized P/L, and the running trade
counter used to generate trade IDs that tie an entry journal row to its
eventual exit row. Persisted as JSON so state survives between daily runs.

This file is the account's single source of truth for "what do we
currently hold." The trade journal (journal.py) is the immutable history
of how we got here; this is just the current snapshot.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import config


@dataclass
class Position:
    trade_id: str
    ticker: str
    shares: float
    entry_price: float
    stop_loss: float
    profit_target: float
    entry_bar_date: str        # ISO date of the signal's last completed bar
    entry_timestamp: str       # ISO datetime the trade was actually opened
    entry_reason: str
    dollars_at_risk: float
    entry_commission: float = 0.0

    def market_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.shares


@dataclass
class Portfolio:
    cash: float = config.STARTING_CAPITAL
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    trade_counter: int = 0
    last_run_date: Optional[str] = None
    starting_capital: float = config.STARTING_CAPITAL

    def next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:04d}"

    def equity(self, mark_prices: dict[str, float]) -> float:
        positions_value = sum(
            pos.market_value(mark_prices.get(ticker, pos.entry_price))
            for ticker, pos in self.positions.items()
        )
        return self.cash + positions_value

    def open_position(self, pos: Position, cost: float) -> None:
        if cost > self.cash + 1e-9:
            raise ValueError(f"Insufficient cash: need {cost}, have {self.cash}")
        self.cash -= cost
        self.positions[pos.ticker] = pos

    def close_position(self, ticker: str, proceeds: float, pnl: float) -> Position:
        pos = self.positions.pop(ticker)
        self.cash += proceeds
        self.realized_pnl += pnl
        return pos

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Portfolio":
        positions = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        return cls(
            cash=d["cash"],
            positions=positions,
            realized_pnl=d.get("realized_pnl", 0.0),
            trade_counter=d.get("trade_counter", 0),
            last_run_date=d.get("last_run_date"),
            starting_capital=d.get("starting_capital", config.STARTING_CAPITAL),
        )

    def save(self, path: Optional[Path] = None) -> None:
        path = path or config.PORTFOLIO_STATE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        tmp_path.replace(path)  # atomic on POSIX

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Portfolio":
        path = path or config.PORTFOLIO_STATE_PATH
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text()))
