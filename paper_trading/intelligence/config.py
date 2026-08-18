"""
Tunables for the intelligence layer. Kept separate from
papertrader/config.py (which still governs the mechanical paper-trading
engine: risk %, stop/target math, commission/slippage) so the two layers
can be tuned independently.
"""

from __future__ import annotations

from pathlib import Path

# --- Universe --------------------------------------------------------
# CORE_UNIVERSE: the original 16 liquid, well-known large-caps. These
# always get the FULL treatment every day -- EDGAR filings, options
# snapshot, and full early-signal/convergence/opportunity scoring --
# regardless of whether the scanner flags anything, since the list is
# small and cheap.
CORE_UNIVERSE = [
    "SPY", "QQQ", "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA", "META", "JPM", "V",
    "AMD", "TSLA", "PLTR", "COIN", "SMCI", "AVGO",
]

# WIDE_UNIVERSE: ~450 liquid small/mid/large-cap stocks + theme ETFs
# (intelligence/universe.py), added so early-footprint/momentum discovery
# isn't limited to famous mega-caps. Every one of these gets scanned
# cheaply (batched price/volume fetch) every day, but only the ones the
# scanner flags as NOTABLE get promoted to the expensive EDGAR/options/
# full-scoring path -- see SHORTLIST_MAX_FROM_WIDE below and
# intel_engine.py's two-stage funnel. This is what keeps ~450 tickers
# "computationally lightweight": the expensive per-ticker network calls
# (EDGAR, options chains) only ever run for a capped shortlist, not the
# whole universe, every day.
from .universe import WIDE_UNIVERSE  # noqa: E402

CANDIDATE_UNIVERSE = list(dict.fromkeys(CORE_UNIVERSE + WIDE_UNIVERSE))

# How many WIDE_UNIVERSE tickers (beyond the always-enriched CORE_UNIVERSE)
# can be promoted to the expensive EDGAR/options/full-scoring path per
# day, ranked by scanner.quick_score(). Raise this later if the account
# and results justify more daily API calls; kept modest for now per the
# "computationally lightweight" requirement.
SHORTLIST_MAX_FROM_WIDE = 40

# Indices, rates, dollar, commodities, crypto -- observed, never traded.
MACRO_TICKERS = {
    "sp500": "SPY",
    "nasdaq100": "QQQ",
    "russell2000": "IWM",
    "vix": "^VIX",
    "us10y_yield": "^TNX",   # quoted as yield x10, e.g. 42.5 = 4.25%
    "dollar_index": "DX-Y.NYB",
    "wti_crude": "CL=F",
    "brent_crude": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "bitcoin": "BTC-USD",
    "uranium_etf": "URA",   # free proxy; no liquid free uranium future
}

# Sector ETFs -- observed for rotation; also individually tradeable if a
# sector itself throws a scanner/convergence signal.
SECTOR_ETFS = {
    "Technology": "XLK",
    "Semiconductors": "SMH",
    "Energy": "XLE",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Biotech": "XBI",
    "Industrials": "XLI",
    "Defense": "ITA",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Small Caps": "IWM",
}

BENCHMARK_TICKER = "SPY"

# --- Scanner thresholds ------------------------------------------------
REL_VOLUME_LOOKBACK_DAYS = 20
REL_VOLUME_ELEVATED = 1.5     # today's volume >= 1.5x the 20d average
REL_VOLUME_HIGH = 2.5
GAP_PCT_NOTABLE = 3.0          # open vs prior close, percent
RANGE_BREAKOUT_LOOKBACK_DAYS = 20
ACCEL_LOOKBACK_DAYS = 5        # for price/volume acceleration comparisons

# --- SEC EDGAR -----------------------------------------------------------
# SEC requires a descriptive User-Agent identifying the requester for
# automated access (see sec.gov/os/webmaster-faq#developers). Put a real
# contact of YOUR choosing here before running -- it does not have to be
# your personal email, just something SEC could use to reach the operator
# of this script if it needs to. Left as a placeholder deliberately; never
# auto-filled with a user's personal address.
SEC_EDGAR_CONTACT = "paper-trading-experiment contact@example.com"
EDGAR_FILING_LOOKBACK_DAYS = 10
EDGAR_FORM_TYPES_OF_INTEREST = ["8-K", "4", "S-1", "S-3", "SC 13D", "SC 13G"]

# --- Options (degraded/free-tier) snapshot ------------------------------
OPTIONS_VOL_OI_ELEVATED_RATIO = 3.0
OPTIONS_MIN_PREMIUM_NOTIONAL = 5_000  # ignore contracts too small to matter

# --- Catalyst calendar ---------------------------------------------------
CALENDAR_FORWARD_DAYS = 14
EARNINGS_LOOKAHEAD_DAYS = 30  # how far ahead to pull earnings dates from yfinance

# --- Scoring ---------------------------------------------------------
CONVERGENCE_MIN_INDEPENDENT_CATEGORIES = 3
EARLY_SIGNAL_MOVE_ALREADY_HAPPENED_PCT = 20.0  # 20d gain beyond which "early" starts to fail

# Alert levels, for reference (see scoring/opportunity.py for assignment logic)
ALERT_WATCH = "WATCH"
ALERT_DEVELOPING = "DEVELOPING"
ALERT_HIGH_CONVICTION_WATCH = "HIGH_CONVICTION_WATCH"
ALERT_ACTIONABLE = "ACTIONABLE_PAPER_TRADE_SETUP"

# A 🔴 ACTIONABLE alert additionally requires the opportunity score to
# clear this bar -- high score alone from section 13 means INVESTIGATE,
# not BUY; this is the separate, higher bar for actually risking capital.
ACTIONABLE_MIN_OPPORTUNITY_SCORE = 75
ACTIONABLE_MIN_CONVERGENCE_SCORE = 65

# --- Paths -----------------------------------------------------------
INTEL_DIR = Path(__file__).resolve().parent.parent
LEARNING_DB_PATH = INTEL_DIR / "data" / "learning.db"
