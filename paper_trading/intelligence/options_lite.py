"""
Options intelligence (spec §6), degraded to what's actually available for
free: a point-in-time snapshot of volume/open-interest/IV per contract
(via yfinance), NOT time-and-sales, NOT aggressor-side execution, NOT
sweep detection. True "whale flow" (who lifted the offer, repeated
sweeps, opening vs. closing) requires a paid feed (Unusual Whales,
Cheddar Flow, etc.) that this system does not have.

Every output here is labeled OPTIONS SNAPSHOT (free tier) so it's never
confused with real flow data downstream. Per the explicit spec rule, a
big call is never assumed bullish -- direction is reported as a
call/put volume skew fact, with an explicit caveat that a large trade
may be a hedge, a spread leg, or a closing trade.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from papertrader.data_source import DataUnavailableError
from . import config
from .data_providers import OptionChain, OptionContract, OptionsDataProvider

DIRECTION_INDETERMINATE = "INDETERMINATE"
DIRECTION_CALL_SKEWED = "CALL_SKEWED"
DIRECTION_PUT_SKEWED = "PUT_SKEWED"

CAVEAT = (
    "OPTIONS SNAPSHOT (free tier): volume/open-interest at time of fetch only. "
    "Not sweep/aggressor data. A large trade may be a hedge, a spread leg, "
    "market-maker activity, or a closing trade -- size alone does not imply direction."
)


@dataclass
class UnusualContract:
    ticker: str
    expiration: str
    strike: float
    contract_type: str
    volume: int
    open_interest: int
    vol_oi_ratio: float
    approx_notional: float
    implied_volatility: float


@dataclass
class OptionsSnapshotResult:
    ticker: str
    as_of: dt.datetime
    unusual_contracts: list[UnusualContract]
    call_volume: int
    put_volume: int
    direction_skew: str
    whale_flow_score: int   # 0-100; NOT a directional confidence, purely "how unusual"
    caveat: str = CAVEAT
    error: Optional[str] = None


def _score_chain(unusual: list[UnusualContract], call_vol: int, put_vol: int) -> int:
    if not unusual:
        return 0
    max_ratio = max(c.vol_oi_ratio for c in unusual)
    max_notional = max(c.approx_notional for c in unusual)
    concentration = len(unusual)  # how many contracts independently look unusual

    ratio_component = min(max_ratio / 8.0, 1.0) * 35
    notional_component = min(max_notional / 100_000, 1.0) * 35
    concentration_component = min(concentration / 5.0, 1.0) * 30

    return round(ratio_component + notional_component + concentration_component)


def scan_options(provider: OptionsDataProvider, ticker: str, expirations_to_check: int = 2) -> OptionsSnapshotResult:
    now = dt.datetime.now(tz=dt.timezone.utc)
    try:
        expirations = provider.get_nearest_expirations(ticker, expirations_to_check)
    except DataUnavailableError as e:
        return OptionsSnapshotResult(ticker, now, [], 0, 0, DIRECTION_INDETERMINATE, 0, error=str(e))

    unusual: list[UnusualContract] = []
    total_call_vol = 0
    total_put_vol = 0

    for exp in expirations:
        try:
            chain = provider.get_option_chain(ticker, exp)
        except DataUnavailableError:
            continue

        for contracts in (chain.calls, chain.puts):
            for c in contracts:
                if c.contract_type == "call":
                    total_call_vol += c.volume
                else:
                    total_put_vol += c.volume

                if c.open_interest <= 0 or c.volume <= 0:
                    continue
                ratio = c.volume / c.open_interest
                notional = c.volume * c.last_price * 100
                if ratio >= config.OPTIONS_VOL_OI_ELEVATED_RATIO and notional >= config.OPTIONS_MIN_PREMIUM_NOTIONAL:
                    unusual.append(UnusualContract(
                        ticker=ticker, expiration=exp, strike=c.strike, contract_type=c.contract_type,
                        volume=c.volume, open_interest=c.open_interest, vol_oi_ratio=round(ratio, 2),
                        approx_notional=round(notional, 2), implied_volatility=c.implied_volatility,
                    ))

    total_vol = total_call_vol + total_put_vol
    if total_vol == 0:
        skew = DIRECTION_INDETERMINATE
    else:
        call_share = total_call_vol / total_vol
        if call_share >= 0.70:
            skew = DIRECTION_CALL_SKEWED
        elif call_share <= 0.30:
            skew = DIRECTION_PUT_SKEWED
        else:
            skew = DIRECTION_INDETERMINATE

    score = _score_chain(unusual, total_call_vol, total_put_vol)
    unusual.sort(key=lambda c: c.approx_notional, reverse=True)

    return OptionsSnapshotResult(
        ticker=ticker, as_of=now, unusual_contracts=unusual[:10],
        call_volume=total_call_vol, put_volume=total_put_vol,
        direction_skew=skew, whale_flow_score=score,
    )


def scan_universe_options(provider: OptionsDataProvider, tickers: list[str]) -> list[OptionsSnapshotResult]:
    return [scan_options(provider, t) for t in tickers]
