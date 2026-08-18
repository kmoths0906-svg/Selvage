"""
$130 -> $2,000 experiment tracker (spec §19). Pure measurement -- this
module never feeds back into risk.py or the strategy/scoring layer. It
answers "what would it actually take," not "how do we make it happen."
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from dataclasses import dataclass
from typing import Optional

from papertrader import config as pt_config
from papertrader.portfolio import Portfolio

TARGET_CAPITAL = 2000.0


@dataclass
class TargetTrackerReport:
    starting_capital: float
    target_capital: float
    required_multiple: float
    required_cumulative_return_pct: float
    current_balance: float
    actual_return_pct: float
    max_drawdown_pct: float
    num_closed_trades: int
    days_elapsed: Optional[int]
    risk_per_trade_pct: float
    reward_risk_ratio: float
    illustrative_trades_needed_if_every_trade_won: Optional[int]
    verdict: str


def _max_drawdown_pct(equity_csv_path) -> float:
    if not equity_csv_path.exists():
        return 0.0
    with equity_csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    peak = None
    max_dd = 0.0
    for r in rows:
        eq = float(r["equity"])
        peak = eq if peak is None else max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    return round(max_dd * 100, 2)


def _first_run_date(equity_csv_path) -> Optional[dt.date]:
    if not equity_csv_path.exists():
        return None
    with equity_csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    return dt.datetime.fromisoformat(rows[0]["timestamp"]).date()


def _num_closed_trades(journal_csv_path) -> int:
    if not journal_csv_path.exists():
        return 0
    with journal_csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return sum(1 for r in rows if r["event_type"] == "EXIT")


def build_target_tracker_report(mark_prices: Optional[dict[str, float]] = None) -> TargetTrackerReport:
    mark_prices = mark_prices or {}
    portfolio = Portfolio.load()
    starting = portfolio.starting_capital
    current_balance = round(portfolio.equity(mark_prices), 2)

    required_multiple = round(TARGET_CAPITAL / starting, 3)
    required_cum_return = round((TARGET_CAPITAL - starting) / starting * 100, 2)
    actual_return_pct = round((current_balance - starting) / starting * 100, 4)

    max_dd = _max_drawdown_pct(pt_config.EQUITY_CURVE_PATH)
    num_trades = _num_closed_trades(pt_config.TRADE_JOURNAL_PATH)
    first_date = _first_run_date(pt_config.EQUITY_CURVE_PATH)
    days_elapsed = (dt.date.today() - first_date).days if first_date else None

    # Illustrative, deliberately optimistic upper bound: if every single
    # trade won at exactly the max allowed risk with the standard 2:1
    # reward:risk (a 4% account gain per trade, zero losses -- something
    # no real strategy achieves), how many wins in a row would it take?
    per_win_gain = pt_config.MAX_RISK_PER_TRADE_PCT * pt_config.REWARD_RISK_RATIO
    trades_needed = None
    if per_win_gain > 0 and required_multiple > 1:
        trades_needed = math.ceil(math.log(required_multiple) / math.log(1 + per_win_gain))

    verdict = (
        f"Reaching ${TARGET_CAPITAL:,.0f} from ${starting:,.0f} requires a {required_multiple:.1f}x "
        f"return ({required_cum_return:+.0f}%). Even in the unrealistic best case where every trade "
        f"wins at the full {pt_config.MAX_RISK_PER_TRADE_PCT*100:.0f}% risk with a "
        f"{pt_config.REWARD_RISK_RATIO:.1f}:1 reward (a {per_win_gain*100:.1f}% account gain per trade, "
        f"zero losses), that's {trades_needed} consecutive wins with no losing trades in between -- "
        f"which no real strategy achieves. Risk rules are not being altered to chase this number; "
        f"if the account can't get there within these rules, that is the honest answer, not a reason "
        f"to raise the risk per trade."
    ) if trades_needed else "Insufficient data to compute an illustrative trade count."

    return TargetTrackerReport(
        starting_capital=starting, target_capital=TARGET_CAPITAL, required_multiple=required_multiple,
        required_cumulative_return_pct=required_cum_return, current_balance=current_balance,
        actual_return_pct=actual_return_pct, max_drawdown_pct=max_dd, num_closed_trades=num_trades,
        days_elapsed=days_elapsed, risk_per_trade_pct=pt_config.MAX_RISK_PER_TRADE_PCT * 100,
        reward_risk_ratio=pt_config.REWARD_RISK_RATIO,
        illustrative_trades_needed_if_every_trade_won=trades_needed, verdict=verdict,
    )
