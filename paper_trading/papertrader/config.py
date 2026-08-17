"""
All tunable parameters for the paper-trading experiment live here.

Nothing in this file is fit to historical data. Values were picked from
generally accepted risk-management conventions (the 2% rule, a >=2:1
reward:risk floor, ATR-based stops) before a single trade was placed, and
should stay fixed for the duration of the experiment. If you change a
value mid-experiment, note the date/reason in README.md's changelog so the
journal stays honestly interpretable.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

# --- Account -----------------------------------------------------------
STARTING_CAPITAL = 130.00
TIMEZONE = ZoneInfo("America/New_York")

# --- Risk management -----------------------------------------------------
# Never risk more than this fraction of current equity on a single trade's
# stop-loss distance.
MAX_RISK_PER_TRADE_PCT = 0.02

# A single position may not consume more than this fraction of equity,
# even if the 2% risk math would allow a bigger size (keeps us from going
# all-in on one name with a tight stop).
MAX_POSITION_PCT_OF_EQUITY = 0.60

# Always leave at least this fraction of equity in cash. Enforced when
# sizing new entries.
MIN_CASH_RESERVE_PCT = 0.10

# Don't hold more than this many open positions at once (keeps cash aside
# by construction and limits correlated exposure on a $130 account).
MAX_OPEN_POSITIONS = 2

# Skip a trade if the resulting position would be smaller than this many
# dollars — not worth the round-trip slippage/commission on a tiny account.
MIN_TRADE_DOLLARS = 5.00

# --- Universe: highly liquid, optionable-but-we-won't, large-cap US
# stocks and broad-market ETFs. No penny stocks, no crypto, no leveraged
# or inverse ETFs.
UNIVERSE = [
    "SPY",   # S&P 500 ETF
    "QQQ",   # Nasdaq-100 ETF
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "NVDA",
    "META",
    "JPM",
    "V",
]

MIN_PRICE = 5.00                     # avoid penny-stock-like names
MIN_AVG_DOLLAR_VOLUME = 50_000_000   # 20-day avg dollar volume floor

# --- Strategy parameters (see README.md for the full rationale) --------
TREND_SMA_PERIOD = 50
TREND_SMA_LOOKBACK_FOR_SLOPE = 5   # SMA must be higher now than N sessions ago
PULLBACK_EMA_PERIOD = 10
PULLBACK_LOOKBACK_DAYS = 3         # look for a touch of the EMA within N days
ATR_PERIOD = 14

STOP_ATR_MULT = 1.5
REWARD_RISK_RATIO = 2.0            # profit target = entry + R x stop distance
MAX_HOLD_DAYS = 10                 # time-based exit if neither stop nor target hit

MIN_BARS_REQUIRED = TREND_SMA_PERIOD + TREND_SMA_LOOKBACK_FOR_SLOPE + 5

# --- Simulated execution costs ------------------------------------------
# Most US brokers (incl. Alpaca, Schwab, Fidelity) charge $0 commission on
# stock/ETF trades; kept configurable rather than hard-assumed.
COMMISSION_PER_TRADE = 0.00
# Conservative slippage assumption applied against us on every fill.
SLIPPAGE_BPS = 10   # 0.10%

# --- Paths ---------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

PORTFOLIO_STATE_PATH = DATA_DIR / "portfolio_state.json"
TRADE_JOURNAL_PATH = DATA_DIR / "trade_journal.csv"
REJECTED_SIGNALS_PATH = DATA_DIR / "rejected_signals.csv"
EQUITY_CURVE_PATH = DATA_DIR / "equity_curve.csv"
