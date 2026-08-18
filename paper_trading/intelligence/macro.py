"""
Macro Regime Engine (spec §7) + Cross-Asset Relationship Detector (§8).

Regime classification is a deterministic rule cascade over real returns --
not a model, not a vibe. Every threshold is a module constant below so the
logic is auditable. When nothing clears its bar, the result is
MIXED_UNCLEAR -- the market is not forced into a category just to have an
answer.

Cross-asset "chains" are a fixed set of textbook relationships (e.g. oil
shock -> inflation expectations -> yields -> growth weakness). Each link
is checked against real data and reported TRUE/FALSE with the actual
number; a chain is never assumed to hold just because its first link did.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

from papertrader.data_source import DataUnavailableError, MarketDataProvider
from . import config

# --- Regime thresholds (percent, over the stated lookback) -------------
ENERGY_SHOCK_OIL_10D_PCT = 12.0
INFLATIONARY_GOLD_20D_PCT = 3.0
INFLATIONARY_COPPER_20D_PCT = 3.0
DEFLATIONARY_GOLD_20D_PCT = -3.0
DEFLATIONARY_COPPER_20D_PCT = -3.0
RISK_OFF_VIX_5D_PCT = 15.0
LIQUIDITY_SPREAD_20D_PCT = 5.0  # |IWM 20d return - SPY 20d return|


@dataclass
class AssetMetrics:
    key: str
    ticker: str
    last_close: float
    ret_5d_pct: Optional[float]
    ret_10d_pct: Optional[float]
    ret_20d_pct: Optional[float]
    as_of: dt.date
    error: Optional[str] = None


@dataclass
class RegimeResult:
    regime: str
    confidence: str            # HIGH / MEDIUM / LOW
    evidence: list[str]
    metrics: dict[str, AssetMetrics]
    generated_at: dt.datetime


@dataclass
class ChainLink:
    description: str
    holds: bool
    detail: str


@dataclass
class ChainResult:
    name: str
    status: str   # NOT_TRIGGERED / BROKEN / PARTIALLY_CONFIRMED / CONFIRMED
    links: list[ChainLink]


def _pct_return(bars, days: int) -> Optional[float]:
    if len(bars) < days + 1:
        return None
    close = bars["Close"]
    start = float(close.iloc[-1 - days])
    end = float(close.iloc[-1])
    if start == 0:
        return None
    return round((end - start) / start * 100, 3)


def fetch_macro_metrics(provider: MarketDataProvider, lookback_days: int = 40) -> dict[str, AssetMetrics]:
    metrics: dict[str, AssetMetrics] = {}
    for key, ticker in config.MACRO_TICKERS.items():
        try:
            bars = provider.get_completed_daily_bars(ticker, lookback_days)
            if bars.empty:
                raise DataUnavailableError(f"empty bars for {ticker}")
            metrics[key] = AssetMetrics(
                key=key, ticker=ticker,
                last_close=float(bars["Close"].iloc[-1]),
                ret_5d_pct=_pct_return(bars, 5),
                ret_10d_pct=_pct_return(bars, 10),
                ret_20d_pct=_pct_return(bars, 20),
                as_of=bars.index[-1].date(),
            )
        except DataUnavailableError as e:
            metrics[key] = AssetMetrics(
                key=key, ticker=ticker, last_close=float("nan"),
                ret_5d_pct=None, ret_10d_pct=None, ret_20d_pct=None,
                as_of=dt.date.today(), error=str(e),
            )
    return metrics


def classify_regime(metrics: dict[str, AssetMetrics], now: Optional[dt.datetime] = None) -> RegimeResult:
    now = now or dt.datetime.now(tz=dt.timezone.utc)

    def r(key: str, field_: str) -> Optional[float]:
        m = metrics.get(key)
        return getattr(m, field_) if m and m.error is None else None

    spx_5d, spx_20d = r("sp500", "ret_5d_pct"), r("sp500", "ret_20d_pct")
    qqq_5d = r("nasdaq100", "ret_5d_pct")
    iwm_5d, iwm_20d = r("russell2000", "ret_5d_pct"), r("russell2000", "ret_20d_pct")
    vix_5d = r("vix", "ret_5d_pct")
    yield_20d = r("us10y_yield", "ret_20d_pct")
    dxy_20d = r("dollar_index", "ret_20d_pct")
    wti_10d = r("wti_crude", "ret_10d_pct")
    gold_20d = r("gold", "ret_20d_pct")
    copper_20d = r("copper", "ret_20d_pct")

    have = lambda *xs: all(x is not None for x in xs)

    if have(wti_10d) and wti_10d >= ENERGY_SHOCK_OIL_10D_PCT:
        return RegimeResult(
            "ENERGY_SHOCK", "MEDIUM",
            [f"WTI crude +{wti_10d:.1f}% over 10 sessions (>= {ENERGY_SHOCK_OIL_10D_PCT}% threshold)"],
            metrics, now,
        )

    if have(gold_20d, copper_20d, yield_20d) and (
        gold_20d >= INFLATIONARY_GOLD_20D_PCT and copper_20d >= INFLATIONARY_COPPER_20D_PCT and yield_20d > 0
    ):
        return RegimeResult(
            "INFLATIONARY", "MEDIUM",
            [f"Gold +{gold_20d:.1f}% and copper +{copper_20d:.1f}% over 20 sessions, "
             f"10Y yield proxy +{yield_20d:.1f}% (rising rates alongside rising real-asset prices)"],
            metrics, now,
        )

    if have(gold_20d, copper_20d, yield_20d) and (
        gold_20d <= DEFLATIONARY_GOLD_20D_PCT and copper_20d <= DEFLATIONARY_COPPER_20D_PCT and yield_20d < 0
    ):
        return RegimeResult(
            "DEFLATIONARY", "MEDIUM",
            [f"Gold {gold_20d:.1f}% and copper {copper_20d:.1f}% over 20 sessions, "
             f"10Y yield proxy {yield_20d:.1f}% (falling rates alongside falling real-asset prices)"],
            metrics, now,
        )

    if have(vix_5d, spx_5d, iwm_5d) and vix_5d >= RISK_OFF_VIX_5D_PCT and spx_5d < 0 and iwm_5d < spx_5d:
        return RegimeResult(
            "RISK_OFF", "HIGH",
            [f"VIX +{vix_5d:.1f}% over 5 sessions while SPY {spx_5d:.1f}% and small caps "
             f"underperforming (IWM {iwm_5d:.1f}%)"],
            metrics, now,
        )

    if have(spx_5d, qqq_5d, iwm_5d, vix_5d) and spx_5d > 0 and qqq_5d > 0 and iwm_5d > 0 and vix_5d <= 0:
        return RegimeResult(
            "RISK_ON", "HIGH",
            [f"Broad participation: SPY +{spx_5d:.1f}%, QQQ +{qqq_5d:.1f}%, IWM +{iwm_5d:.1f}%, "
             f"VIX {vix_5d:.1f}% over 5 sessions"],
            metrics, now,
        )

    if have(iwm_20d, spx_20d, dxy_20d):
        spread = iwm_20d - spx_20d
        if spread >= LIQUIDITY_SPREAD_20D_PCT and dxy_20d < 0:
            return RegimeResult(
                "LIQUIDITY_EXPANSION", "LOW",
                [f"Small caps outperforming SPY by {spread:.1f}pp over 20 sessions while the dollar "
                 f"index is down {dxy_20d:.1f}% -- a weak proxy, not a direct liquidity measurement "
                 f"(no free real-time Fed balance sheet / repo data)."],
                metrics, now,
            )
        if spread <= -LIQUIDITY_SPREAD_20D_PCT and dxy_20d > 0:
            return RegimeResult(
                "LIQUIDITY_CONTRACTION", "LOW",
                [f"Small caps underperforming SPY by {spread:.1f}pp over 20 sessions while the dollar "
                 f"index is up {dxy_20d:.1f}% -- a weak proxy, not a direct liquidity measurement."],
                metrics, now,
            )

    missing = [k for k, m in metrics.items() if m.error is not None]
    evidence = ["No single regime's conditions were clearly met."]
    if missing:
        evidence.append(f"DATA UNAVAILABLE for: {', '.join(missing)}")
    return RegimeResult("MIXED_UNCLEAR", "LOW", evidence, metrics, now)


# --- Cross-asset relationship chains -------------------------------------

def _chain_oil_inflation_yields_growth(metrics: dict) -> ChainResult:
    def r(key, f):
        m = metrics.get(key)
        return getattr(m, f) if m and m.error is None else None

    wti_10d = r("wti_crude", "ret_10d_pct")
    gold_10d = r("gold", "ret_10d_pct")
    yield_10d = r("us10y_yield", "ret_10d_pct")
    qqq_10d = r("nasdaq100", "ret_10d_pct")
    spx_10d = r("sp500", "ret_10d_pct")

    links = []
    if wti_10d is None:
        return ChainResult("Oil shock -> inflation expectations -> yields -> growth weakness",
                            "NOT_TRIGGERED", [ChainLink("Oil move (10d)", False, "DATA UNAVAILABLE")])

    trigger = wti_10d >= 5.0
    links.append(ChainLink("WTI crude up >=5% over 10 sessions", trigger, f"WTI 10d = {wti_10d:+.1f}%"))
    if not trigger:
        return ChainResult("Oil shock -> inflation expectations -> yields -> growth weakness", "NOT_TRIGGERED", links)

    ok = gold_10d is not None and gold_10d > 0
    links.append(ChainLink("Gold up (inflation-expectation proxy)", bool(ok),
                            f"Gold 10d = {gold_10d:+.1f}%" if gold_10d is not None else "DATA UNAVAILABLE"))
    if not ok:
        return ChainResult("Oil shock -> inflation expectations -> yields -> growth weakness", "BROKEN", links)

    ok2 = yield_10d is not None and yield_10d > 0
    links.append(ChainLink("Yields rising", bool(ok2),
                            f"10Y yield proxy 10d = {yield_10d:+.1f}%" if yield_10d is not None else "DATA UNAVAILABLE"))
    if not ok2:
        return ChainResult("Oil shock -> inflation expectations -> yields -> growth weakness", "BROKEN", links)

    ok3 = qqq_10d is not None and spx_10d is not None and qqq_10d < spx_10d
    links.append(ChainLink("Growth (QQQ) underperforming broad market (SPY)", bool(ok3),
                            f"QQQ 10d = {qqq_10d:+.1f}%, SPY 10d = {spx_10d:+.1f}%"
                            if qqq_10d is not None and spx_10d is not None else "DATA UNAVAILABLE"))
    return ChainResult(
        "Oil shock -> inflation expectations -> yields -> growth weakness",
        "CONFIRMED" if ok3 else "PARTIALLY_CONFIRMED",
        links,
    )


def _chain_risk_off_flight_to_safety(metrics: dict) -> ChainResult:
    def r(key, f):
        m = metrics.get(key)
        return getattr(m, f) if m and m.error is None else None

    vix_5d = r("vix", "ret_5d_pct")
    yield_5d = r("us10y_yield", "ret_5d_pct")
    gold_5d = r("gold", "ret_5d_pct")
    qqq_5d = r("nasdaq100", "ret_5d_pct")

    links = []
    if vix_5d is None:
        return ChainResult("Risk-off -> VIX spike -> flight to safety (yields down, gold up) -> growth weakness",
                            "NOT_TRIGGERED", [ChainLink("VIX move (5d)", False, "DATA UNAVAILABLE")])

    trigger = vix_5d >= 10.0
    links.append(ChainLink("VIX up >=10% over 5 sessions", trigger, f"VIX 5d = {vix_5d:+.1f}%"))
    if not trigger:
        return ChainResult("Risk-off -> VIX spike -> flight to safety (yields down, gold up) -> growth weakness",
                            "NOT_TRIGGERED", links)

    ok = yield_5d is not None and yield_5d < 0
    links.append(ChainLink("Yields falling (flight to safety)", bool(ok),
                            f"10Y yield proxy 5d = {yield_5d:+.1f}%" if yield_5d is not None else "DATA UNAVAILABLE"))
    ok2 = gold_5d is not None and gold_5d > 0
    links.append(ChainLink("Gold rising", bool(ok2),
                            f"Gold 5d = {gold_5d:+.1f}%" if gold_5d is not None else "DATA UNAVAILABLE"))
    ok3 = qqq_5d is not None and qqq_5d < 0
    links.append(ChainLink("Growth stocks (QQQ) down", bool(ok3),
                            f"QQQ 5d = {qqq_5d:+.1f}%" if qqq_5d is not None else "DATA UNAVAILABLE"))

    confirmed_count = sum(1 for l in links[1:] if l.holds)
    if confirmed_count == 3:
        status = "CONFIRMED"
    elif confirmed_count == 0:
        status = "BROKEN"
    else:
        status = "PARTIALLY_CONFIRMED"
    return ChainResult(
        "Risk-off -> VIX spike -> flight to safety (yields down, gold up) -> growth weakness", status, links
    )


def check_cross_asset_chains(metrics: dict[str, AssetMetrics]) -> list[ChainResult]:
    return [
        _chain_oil_inflation_yields_growth(metrics),
        _chain_risk_off_flight_to_safety(metrics),
    ]
