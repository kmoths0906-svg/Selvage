"""
Simulated broker: turns a quoted price into a realistic fill by applying
a slippage assumption and a commission assumption. Buys fill worse
(higher); sells fill worse (lower) -- slippage always works against us,
never in our favor, so the journal doesn't flatter the strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Fill:
    fill_price: float
    commission: float
    quoted_price: float
    slippage_bps: float


def simulate_buy_fill(quoted_price: float) -> Fill:
    fill_price = quoted_price * (1 + config.SLIPPAGE_BPS / 10_000)
    return Fill(round(fill_price, 4), config.COMMISSION_PER_TRADE, quoted_price, config.SLIPPAGE_BPS)


def simulate_sell_fill(quoted_price: float) -> Fill:
    fill_price = quoted_price * (1 - config.SLIPPAGE_BPS / 10_000)
    return Fill(round(fill_price, 4), config.COMMISSION_PER_TRADE, quoted_price, config.SLIPPAGE_BPS)
