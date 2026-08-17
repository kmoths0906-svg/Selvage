"""
Position sizing. This is the code that enforces the "never risk more than
2% of the account on a single trade" rule -- it is computed once, before
entry, from the planned stop distance, and is never revised after the
fact to make a losing trade look smaller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import config


@dataclass(frozen=True)
class SizingResult:
    shares: float
    position_value: float
    dollars_at_risk: float
    rejected_reason: Optional[str] = None

    @property
    def accepted(self) -> bool:
        return self.rejected_reason is None


def size_position(
    equity: float,
    cash: float,
    entry_price: float,
    stop_price: float,
) -> SizingResult:
    """
    equity: total account value (cash + market value of open positions)
    cash: cash actually available to deploy right now
    entry_price / stop_price: planned levels from the strategy signal
    """

    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        return SizingResult(0.0, 0.0, 0.0, "stop_not_below_entry")

    dollars_at_risk = equity * config.MAX_RISK_PER_TRADE_PCT
    shares_by_risk = dollars_at_risk / risk_per_share
    value_by_risk = shares_by_risk * entry_price

    value_cap_by_position_limit = equity * config.MAX_POSITION_PCT_OF_EQUITY

    reserve_required = equity * config.MIN_CASH_RESERVE_PCT
    cash_deployable = max(cash - reserve_required, 0.0)

    position_value = min(value_by_risk, value_cap_by_position_limit, cash_deployable)

    if position_value < config.MIN_TRADE_DOLLARS:
        return SizingResult(
            0.0, 0.0, 0.0,
            f"position_value_too_small (${position_value:.2f} after caps: "
            f"risk-based=${value_by_risk:.2f}, position-limit=${value_cap_by_position_limit:.2f}, "
            f"cash-available=${cash_deployable:.2f})",
        )

    shares = round(position_value / entry_price, 6)
    position_value = round(shares * entry_price, 2)
    actual_dollars_at_risk = round(shares * risk_per_share, 2)

    return SizingResult(shares, position_value, actual_dollars_at_risk, None)
