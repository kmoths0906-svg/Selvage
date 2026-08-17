# Paper Trading Experiment

A $130 simulated account used to honestly test whether a simple,
explainable swing-trading strategy is worth ever risking real money on.
100% paper trading. No live orders, no real broker connection, no
options/margin/leverage/short-selling/crypto/penny stocks.

This document (written *before* the account placed a single trade) covers:
1. The short-term strategies considered for a small account
2. Which one was chosen, and why
3. The exact entry / exit / risk / sizing rules
4. The market-data source and why
5. The architecture and file layout
6. How to run it, and an important note about this sandbox's network access

---

## 1. Strategies considered

| Approach | Why it was set aside for this account |
|---|---|
| **Intraday day trading / scalping** | The Pattern Day Trader (PDT) rule requires $25k equity in a margin account to place 4+ day trades in 5 rolling business days. A $130 account either can't do this legally with real money later, or would be forced into a cash account with slow trade-settlement (T+1) that makes rapid re-entry impractical. Also, $0.10–$1 spreads/slippage eat a much larger % of a tiny account on quick in-and-out trades. |
| **Options strategies (covered calls, spreads, etc.)** | Explicitly excluded by the brief. Also generally unsuitable for a $130 account (contract sizes, defined-risk spreads still often cost more than $130 in margin/collateral). |
| **Momentum/breakout day trading on small caps** | Small/low-priced ("penny") stocks are explicitly excluded, and momentum breakouts are notoriously prone to false signals and require constant intraday attention that isn't compatible with an honest, mechanical, no-look-ahead system. |
| **Mean reversion on oversold RSI (buy any big dip)** | Can work, but "buy the biggest dip" strategies tend to catch falling knives in genuine downtrends without a trend filter — hard to distinguish a real edge from noise in a short experiment. |
| **Trend-following pullback ("buy the dip in a confirmed uptrend")** | **Chosen.** See below. |

## 2. Chosen strategy and why

**Daily-bar trend-following pullback, held for multiple days (a "swing trade"), not a day trade.**

Reasons:
- **No PDT exposure.** Positions are opened and closed at least one full session apart, so this never risks tripping the Pattern Day Trader rule if real money is used later.
- **One decision per day.** Signals are generated once, from that day's completed bar, after the close. This is naturally compatible with a strict no-look-ahead rule and doesn't require watching a screen intraday.
- **Explainable in one sentence per trade.** "Price is in a confirmed uptrend, pulled back to its short-term average, and just showed the first sign of resuming the trend" — every trade's reasoning is auditable in plain English (see `strategy.py`'s `reason` string, written verbatim into the journal).
- **Trend + pullback has a real, if modest, statistical basis** in equity markets (momentum/trend persistence is one of the more replicated market anomalies), as opposed to strategies invented purely to look good on a backtest.
- **Fits a small account.** Fractional shares mean position size is set by risk math, not by how many whole shares $130 can buy.

This is *not* presented as a guaranteed-profitable strategy — it's a reasonable, well-known, honestly-testable starting point. The whole point of the experiment is to find out, with real (paper) trades, whether it's actually good enough to risk real money on.

## 3. Exact rules

**Universe:** a fixed list of 10 highly liquid large-cap US stocks/ETFs (`config.UNIVERSE`): `SPY, QQQ, AAPL, MSFT, AMZN, GOOGL, NVDA, META, JPM, V`. Filters applied to every candidate before any signal is even considered:
- Price ≥ $5 (no penny stocks)
- 20-day average dollar volume ≥ $50,000,000 (tight spreads, easy fills)

**Entry signal** (evaluated once per ticker per day, on the most recently *completed* daily bar only):
1. **Uptrend confirmed:** close > 50-day SMA, and the 50-day SMA is higher than it was 5 sessions ago.
2. **Pullback:** the session low touched or dipped below the 10-day EMA at some point in the last 3 sessions.
3. **Reversal confirmation:** today's close > today's open (bullish candle) AND today's close > yesterday's close.

If all three hold, a `Signal` is generated and timestamped at the moment the code runs (`datetime.now()` in US/Eastern), referencing the completed bar's date. Execution happens against the *live* price the next time the engine runs — never against the historical close used to generate the signal.

**Stop-loss:** `entry_price − 1.5 × ATR(14)`, where ATR(14) is computed as of the signal day and locked in at entry (never recalculated after the fact).

**Profit target:** `entry_price + 2.0 × (entry_price − stop_loss)` — a fixed 2:1 reward-to-risk floor.

**Time-based exit:** if neither stop nor target is hit within 10 trading days, the position is closed at the current market price ("no dead capital" rule).

**Position sizing (the 2% rule):**
```
dollars_at_risk   = account_equity × 2%
shares            = dollars_at_risk / (entry_price − stop_loss)
position_value    = shares × entry_price, capped so that:
                       - no single position exceeds 60% of equity
                       - cash never drops below 10% of equity
```
Fractional shares are allowed and used (rounded to 6 decimal places, matching what fractional-share brokers like Alpaca/Schwab/Fidelity support).

**Portfolio-level risk:** at most 2 open positions at once (by construction this keeps cash in reserve — never "all in" on one idea), max 60% of equity in any single name, minimum 10% cash reserve always maintained.

**Transaction costs:** most $0-commission US brokers exist today, so commission defaults to $0.00 (configurable in `config.COMMISSION_PER_TRADE`). A conservative 0.10% slippage assumption is applied against every fill in both directions (buys fill slightly worse/higher, sells fill slightly worse/lower) via `broker_sim.py`, so results are not flattered by assuming perfect fills.

**No look-ahead, concretely enforced (not just promised):**
- `data_source.get_completed_daily_bars()` contractually excludes any session that hasn't finished yet — verified by a same-day check against US market close.
- The strategy function (`strategy.evaluate`) is a pure function of the bars it's given; it never fetches data itself.
- Entries/exits execute against `get_latest_price()` — the real quote *at the moment the engine runs* — never a historical value.
- The trade journal and rejected-signal log are **append-only** (`journal.py` only ever opens files in append mode, one new row per event). There is no code path that edits or deletes a past row. Every row is timestamped when it was written.
- There is deliberately **no backtester** in this codebase. This system only ever looks forward from "now."

## 4. Market-data source

**Primary: [yfinance](https://github.com/ranaroussi/yfinance)** (unofficial Yahoo Finance client), via `papertrader.data_source.YFinanceProvider`.
- **No account or API key required** — this is why it's the default; it lets the experiment start immediately.
- Provides free daily OHLCV bars and a reasonably current last-traded price, which is all this end-of-day strategy needs.
- Caveat: it's an unofficial wrapper around Yahoo's public endpoints (not a documented, contractually-supported API), and quotes can be delayed a few minutes. Fine for a daily-decision swing strategy; **not** a foundation to build a latency-sensitive system on.

**Recommended upgrade path if this goes toward real money: [Alpaca](https://alpaca.markets/) Market Data API.**
- Requires a free account and an API key (paper-trading keys are free and separate from any real-money keys).
- Officially supported, has a real terms of service, and — usefully — the same account also offers commission-free fractional-share paper *and* live trading, so the execution model in `broker_sim.py` could eventually be swapped for real Alpaca paper-trading orders with minimal change, before ever touching real money.
- `data_source.py` defines `MarketDataProvider` as an abstract interface specifically so this swap is a matter of writing one new class, not rewriting the strategy/engine/risk code.

## 5. Architecture

```
paper_trading/
├── README.md                  # this file
├── requirements.txt
├── run_daily.py                # CLI entrypoint: init / run / report
├── papertrader/
│   ├── config.py                # every tunable parameter, fixed before trading began
│   ├── data_source.py           # MarketDataProvider interface, YFinanceProvider, FakeDataProvider (tests)
│   ├── strategy.py               # the pullback signal generator (pure function, no I/O)
│   ├── risk.py                   # 2% risk rule + position sizing
│   ├── broker_sim.py             # simulated fills: slippage + commission
│   ├── portfolio.py              # account state (cash, positions, realized P/L), JSON-persisted
│   ├── journal.py                # append-only CSV logs: trades + rejected signals + equity curve
│   ├── engine.py                 # daily orchestration: check exits -> look for one entry -> log -> persist
│   └── report.py                 # reads the journal/state and builds the dashboard
├── tests/
│   └── test_engine.py            # offline tests using synthetic data (see note below)
└── data/                          # generated/append-only state — the actual experiment record
    ├── portfolio_state.json       # current snapshot: cash, open positions, realized P/L
    ├── trade_journal.csv          # every entry/exit, immutable, one row per event
    ├── rejected_signals.csv       # every signal considered and rejected, with reason
    └── equity_curve.csv           # one row per day the engine ran, for drawdown tracking
```

Data flow for one daily run (`run_daily.py run`):
`YFinanceProvider` → `engine.run()` → for each open position, check stop/target/max-hold against the live quote (`broker_sim` simulates the fill) → for the universe, ask `strategy.evaluate()` for a signal off completed bars only → if accepted, `risk.size_position()` sizes it under the 2% rule → `broker_sim` simulates the entry fill → `portfolio` updates cash/positions → `journal` appends the immutable record → `portfolio.save()` persists state.

## 6. Running it

```bash
cd paper_trading
pip install -r requirements.txt

python run_daily.py init      # one-time: creates the $130 account
python run_daily.py run       # run once per trading day (after ~4pm ET is safest)
python run_daily.py report    # print the dashboard
```

Run `run_daily.py run` once per trading day going forward — that's the entire "operate the experiment" loop. It's idempotent (a second run the same day is a no-op unless you pass `--force`, which you should only do for debugging, never to "retry" a trade you didn't like).

### A note on this sandbox's network access

This code was developed and unit-tested inside an isolated cloud session whose outbound network policy blocks Yahoo Finance and every other market-data host tried (confirmed via direct `curl` — each returns a 403 at the network gateway). That means **`YFinanceProvider` has not been exercised against live data in this environment**, only against a synthetic `FakeDataProvider` in `tests/test_engine.py`, which validates the exact same signal-generation → risk-sizing → execution → journaling code path with deterministic fake price series (including a forced stop-loss exit) instead of a live feed.

Run `python run_daily.py run` on a machine with normal internet access (your own laptop, a cron job, a CI runner with network egress, etc.) for it to actually fetch real market data and place real (paper) trades. The `data/` files here start empty/uninitialized for that reason — the first real entry in `trade_journal.csv` should be an honest trade made with real data, not something fabricated in this session.

### Changelog
- 2026-08-17: initial strategy and system built. No trades placed yet — the experiment starts on the first real `run` invoked from an environment with market-data access.
