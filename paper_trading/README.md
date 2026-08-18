# Paper Trading Experiment

A $130 simulated account used to honestly test whether a market-intelligence
and early-opportunity-detection system can find real, tradeable footprints
*before* a move becomes obvious — and whether any of it is worth ever
risking real money on. 100% paper trading. No live orders, no real broker
connection, no options/margin/leverage/short-selling/crypto/penny stocks.

**Primary question the system exists to answer:** *where is something
unusual beginning to happen that most traders may not have noticed yet?*
Not "predict the market" — detect footprints, log the evidence, paper
trade only the strongest convergences, and measure afterward whether any
of the signals actually predicted anything.

**Run this daily:** `python run_intel.py daily` (see "Running it" below).
The original single-strategy engine (`run_daily.py`) still works
standalone and shares the same $130 account.

---

# Part A — Original strategy (still available, unchanged)

This is the system built first: one mechanical, explainable swing-trading
strategy with nothing else around it. It's preserved exactly as built —
nothing here was touched by the Part B expansion — and remains runnable
on its own via `run_daily.py`.

## A1. Strategy: daily-bar trend-following pullback

**Entry** (evaluated once per ticker per day, on the most recently
*completed* daily bar only):
1. **Uptrend confirmed:** close > 50-day SMA, and the 50-day SMA is higher than it was 5 sessions ago.
2. **Pullback:** the session low touched or dipped below the 10-day EMA within the last 3 sessions.
3. **Reversal confirmation:** today's close > today's open AND > yesterday's close.

**Stop-loss:** `entry − 1.5 × ATR(14)`. **Target:** `entry + 2.0 × (entry − stop)`.
**Time exit:** close after 10 trading days if neither hit. **Sizing:** 2% risk rule (see Part C).

Why this one, of several considered (day trading, options, small-cap
momentum, RSI mean-reversion): no PDT exposure (positions held overnight,
never same-day), one decision per day compatible with strict no-look-ahead,
explainable in one sentence per trade, and momentum/trend persistence has
a real (if modest) statistical basis rather than being reverse-engineered
from a backtest.

`papertrader/strategy.py` is a pure function of the bars it's given — it
never fetches data itself, which is what makes it auditable for
look-ahead bias. See the module docstrings in `papertrader/` for the rest.

---

# Part B — Market Intelligence, Early-Opportunity Detection & Convergence System

Built on top of Part A without modifying it (one shared refactor:
`papertrader/engine.py`'s exit-checking logic was extracted into a
reusable `check_exits()` function so the new orchestrator could call the
same tested code instead of duplicating it — no behavior change, covered
by the existing tests).

## B1. What it does

Each day, before anything gets traded:
1. Classifies the **macro regime** (RISK_ON / RISK_OFF / ENERGY_SHOCK /
   INFLATIONARY / DEFLATIONARY / LIQUIDITY_EXPANSION / LIQUIDITY_CONTRACTION
   / MIXED_UNCLEAR) from real index/rate/commodity/crypto data — never
   forced into a category when the evidence doesn't clearly support one.
2. Checks a few textbook **cross-asset chains** (e.g. oil shock → inflation
   expectations → yields → growth weakness) link by link against real
   data, reporting exactly which links held and which broke.
3. Ranks **sector rotation** (13 sector ETFs vs. SPY, multiple lookbacks).
4. Runs the **daily scanner** over a ~465-ticker universe (relative
   volume, gaps, price/volume acceleration, range breakouts, a
   volume-normalized accumulation/distribution trend, relative strength
   vs. SPY) — deliberately wide, not just famous mega-caps, since
   early-footprint/momentum discovery is a primary objective and unusual
   activity is more informative (and more common) in less-followed
   names. See B3.5 for how this stays computationally lightweight.
5. Pulls **SEC EDGAR filings** (8-K, Form 4, S-1/S-3, 13D/13G) as sourced,
   timestamped, CONFIRMED catalysts, classified by likely impact — for
   the shortlist (see B3.5), not the whole universe.
6. Pulls a **free-tier options snapshot** (volume/OI per contract) —
   explicitly labeled as NOT sweep/whale data, since that requires a paid
   feed this system doesn't have — also shortlist-only.
7. Cross-references the **14-day forward catalyst calendar** against
   today's activity for **pre-catalyst alerts**.
8. Scores every candidate: **Early-Signal** (are we early or chasing?),
   **Convergence** (how many genuinely independent evidence categories
   agree?), **Opportunity** (0-100, "investigate" not "buy").
9. Assigns an alert level (🟢 WATCH / 🟡 DEVELOPING / 🟠 HIGH CONVICTION
   WATCH / 🔴 ACTIONABLE) and, only for 🔴 with long-only bullish evidence,
   executes a paper trade through the **same** `papertrader` risk/broker
   sim/portfolio/journal code Part A uses — never a reimplementation.
10. Logs everything — every candidate, every alert, every rejection — to
    a SQLite learning database (`learning_db.py`) so performance can
    eventually be broken down by signal type, catalyst type, sector,
    regime, and convergence combination.

## B2. Data-source honesty matrix

| Category | Status | Source |
|---|---|---|
| Price/volume/gaps/rel-volume/breakouts/volatility/accumulation | **Free, live** | yfinance |
| Sector rotation, macro (SPX/Nasdaq/Russell/VIX/yields/DXY/oil/gold/silver/copper/BTC) | **Free, live** | yfinance |
| SEC filings (8-K/Form 4/S-1/S-3/13D/13G) | **Free, live, official** | SEC EDGAR (`data.sec.gov`, no key) |
| Earnings dates | **Free, live, best-effort** | yfinance (third-party sourced; can be wrong/missing) |
| Options volume/OI snapshot | **Free, live, but degraded** | yfinance option chain — a point-in-time snapshot, NOT sweep/aggressor data |
| "Whale flow" (true sweeps, aggressor side) | **Not available** | Requires a paid feed (Unusual Whales, Cheddar Flow, etc.) — not subscribed, will not be without asking first |
| Short interest | **Not real-time** | FINRA's free files are ~2 weeks stale; not used for scoring |
| FOMC/CPI/PPI/jobs-report dates | **Hand-researched, static, dated** | Claude used WebSearch against federalreserve.gov/bls.gov once (2026-08-18) — see `catalysts/macro_calendar_seed.py`; needs manual refresh, does not auto-update |
| FDA PDUFA/adcomm dates | **Not available** | No free structured API |
| Geopolitical/resource monitoring | **Not automated** | No structured free source; best done as an ad hoc research question, not a scanner |
| Social media (X/Reddit/TikTok/Discord) | **Not automated** | No viable free API at scale; works as a manual verify-a-claim workflow (`social_verifier.py`) instead |

## B3. Architecture

```
paper_trading/
├── papertrader/            # Part A — unchanged except one extraction (check_exits)
├── intelligence/
│   ├── config.py             # CORE_UNIVERSE, WIDE_UNIVERSE import, shortlist cap, all Phase 1 tunables
│   ├── universe.py            # the ~450-ticker small/mid/large-cap + theme-ETF list (see B3.5)
│   ├── data_providers.py     # SecEdgarProvider, YFinanceOptionsProvider (+ Fake doubles for tests)
│   ├── macro.py               # regime engine + cross-asset chain checker
│   ├── sectors.py             # sector rotation / relative strength
│   ├── scanner.py             # daily scanner metrics + is_notable/quick_score (shortlisting)
│   ├── edgar.py                # SEC filing -> classified Catalyst
│   ├── options_lite.py        # free-tier options snapshot + weak whale-flow score
│   └── universe_validation.py # ticker health state machine (see B3.6) -- zero extra requests
├── catalysts/
│   ├── models.py               # shared Catalyst dataclass
│   ├── macro_calendar_seed.py  # hand-researched FOMC/CPI/PPI/jobs dates (see B2)
│   ├── calendar.py              # merges seed + live earnings + EDGAR into the 14-day forward view
│   └── pre_positioning.py       # cross-references the calendar against scanner/options activity
├── scoring/
│   ├── early_signal.py          # 0-100: early vs. already-obvious
│   ├── convergence.py            # 0-100: independent-category agreement (never double-counted)
│   └── opportunity.py            # 0-100 overall + alert-level assignment
├── learning_db.py            # SQLite: candidates, alerts, convergence alerts, pre-catalyst alerts,
│                              #   rejections, social verifications, retrospective tests, ticker validation
├── intel_engine.py            # daily orchestrator -- the ONLY place a candidate becomes a trade
├── intel_report.py            # the short (max-5-opportunity) daily report
├── retrospective.py           # anti-hindsight historical testing harness
├── social_verifier.py         # data model + checklist for verifying social-media claims
├── target_tracker.py          # $130 -> $2,000 math, measured honestly, never gamed
├── run_intel.py                # CLI: `daily` (+ --diagnostics) and `revalidate-quarantine`
├── run_daily.py                 # CLI: Part A's original init/run/report, still works standalone
└── tests/                      # 68 offline tests (synthetic data; see note on network access below)
```

## B3.5. Wide universe, kept computationally lightweight

`CANDIDATE_UNIVERSE` (`intelligence/config.py`) = `CORE_UNIVERSE` (the
original 16 liquid mega-caps) + `WIDE_UNIVERSE` (`intelligence/universe.py`,
~450 liquid small/mid/large-cap stocks and theme ETFs). Everything in it
gets scanned every day — but scanning (price/volume math on bars already
in memory) is cheap; EDGAR filings and options chains are not, at
hundreds of tickers a day.

So there's a two-stage funnel, every run:
1. **Scan everything, cheaply.** `YFinanceProvider.prefetch_daily_bars()`
   batches the ~465-ticker fetch into a handful of `yf.download()` calls
   (chunked, threaded) instead of one request per ticker, then
   `scanner.scan_universe()` runs off that in-memory cache.
2. **Shortlist.** `CORE_UNIVERSE` is always fully enriched. From
   `WIDE_UNIVERSE`, only tickers the scanner flags `is_notable()`
   (elevated relative volume, a breakout/breakdown, price acceleration,
   or a genuine accumulation/distribution trend) get promoted, ranked by
   `scanner.quick_score()` and capped at `SHORTLIST_MAX_FROM_WIDE` (40).
3. **Enrich the shortlist only.** SEC EDGAR filings, the options
   snapshot, and the full early-signal/convergence/opportunity scoring
   pass all run only on the shortlist (at most 16 + 40 = 56 tickers),
   not the full ~465. Everything scanned-but-not-shortlisted still gets
   a one-line entry in the learning database (`rejected_candidates`) so
   the record stays complete, just without the expensive per-ticker work.

Raise `SHORTLIST_MAX_FROM_WIDE`, or widen `WIDE_UNIVERSE` itself, once
performance data justifies spending more daily API calls — this was
explicitly built to expand later, not as a final number.

**Universe curation, honestly:** there is no free, live, market-wide
screener API (see the honesty matrix above), so `intelligence/universe.py`
was hand-compiled by Claude from training knowledge of real, currently-
listed US tickers — not fetched from a live index feed, and not
fabricated (ticker symbols are static company identity, not "market
data" in the sense the no-fabrication rule is about). Some entries may
have since been acquired, delisted, or renamed; that's handled by the
same per-ticker `DataUnavailableError` path every other data gap uses —
logged and skipped, not a crash. The list needs periodic manual refresh,
same as the macro calendar seed.

## B3.6. Universe validation

Since `intelligence/universe.py` was hand-compiled rather than pulled
from a live index feed, some tickers on it may already be wrong (acquired,
delisted, renamed). `intelligence/universe_validation.py` tracks each
ticker's health in a `ticker_validation` SQLite table with one of:

- `ACTIVE` — fetched cleanly, fresh, has volume.
- `TEMPORARY_DATA_FAILURE` — failed today; may just be a blip.
- `STALE` — data fetched, but the bars are old (>5 calendar days) or
  show no measurable 20-day average volume.
- `POSSIBLY_DELISTED` — failed 5+ consecutive days.
- `QUARANTINED` — failed (or stayed stale) 10+ consecutive days.
  Excluded from every future scan until manually revalidated.
- `RENAMED_MERGED` — only ever set explicitly (see below), never inferred.

**A ticker is never dropped after one bad day** — every escalation
requires that many *consecutive* failures, reset to zero by any success.

**Zero extra network requests.** This does not run as a separate
validation sweep. It updates from the exact `ScanResult`s the daily
scan already produces — the "small local validation cache" the point of
which is to *avoid* re-checking tickers, not to add a new check. The
only thing this costs a request for is `revalidate-quarantine`
(`python run_intel.py revalidate-quarantine`), a separate, explicitly-
invoked, low-frequency maintenance command that does one real fetch per
currently-quarantined ticker to see if any recovered — never run
automatically.

**Replacement tickers are never guessed.** There's no free API that
reliably maps an old ticker to what it became after a rename or merger.
`universe_validation.record_replacement_ticker(conn, old, new, note)` is
the only way `RENAMED_MERGED` or a `replacement_ticker` value ever gets
set — a deliberate call with a real, cited reason, made by a human or by
Claude after doing actual research, never inferred from failure patterns.

## B4. Scoring, in brief

**Early-Signal (0-100):** baseline 50, then adjusted for how much the
ticker has already moved (20d return — a big prior move is a penalty,
not a bonus), whether relative volume looks like attention just starting
vs. already exploded, whether there's a catalyst in the last 1-5 days
the market hasn't fully reacted to, and whether a range breakout looks
fresh vs. extended. A quiet stock with several of these can outscore one
that already ran 100%.

**Convergence (0-100) — the most important score.** Counts how many of
five **independent** evidence categories are positive: `CATALYST`,
`PRICE_VOLUME` (the scanner — one category regardless of how many
sub-signals fire, so correlated measurements don't get counted twice),
`OPTIONS_FLOW`, `SECTOR_STRENGTH`, `MACRO_ALIGNMENT`. A genuine
🚨 CONVERGENCE ALERT requires ≥3.

**Opportunity (0-100):** a weighted blend of catalyst quality, early-signal,
convergence, volume behavior, a rough setup-quality proxy, and liquidity,
minus a dilution penalty if a recent filing suggests share issuance.
**High score means INVESTIGATE, not BUY.**

**🔴 ACTIONABLE requires all of:** opportunity ≥ 75, convergence ≥ 65,
a genuine convergence alert (≥3 categories), *and* long-only bullish
evidence (a breakout or positive price acceleration — this system never
shorts). In testing, hitting this bar reliably took 4-5 stacked
independent categories, not one or two — which is the intended
conservatism, not a bug.

## B5. What Part B deliberately does NOT do yet (Phase 1 honesty)

- **The original pullback strategy (Part A) is not yet cross-wired into
  the convergence engine** as its own confirming signal category. It
  still runs completely standalone via `run_daily.py`. Folding it in as
  a `TECHNICAL_PATTERN` category is a reasonable Phase 2 addition.
- **No partial/scaled exits.** Every position has one stop and one
  target (Target 2 from the spec isn't implemented) — `papertrader`'s
  position model is all-or-nothing by design, and changing that is a
  structural change, not a Phase 1 one.
- **Retrospective testing (`retrospective.py`) can only replay
  price/volume evidence** plus any catalysts *you* supply with real
  historical dates — there's no historical point-in-time snapshot of
  options chains or EDGAR filings available, so those categories are
  unavailable retrospectively even though they're live in production.
- **No FDA calendar, no live economic-calendar API, no geopolitical
  scanner, no true options sweep/whale data.** All would require either
  a paid API or work that goes beyond what "free, no signup" allows —
  see the honesty matrix above. None will be added without asking first.

## B6. SEC EDGAR setup

`SecEdgarProvider` requires a descriptive `User-Agent` per SEC's
automated-access policy (`intelligence/config.py`'s `SEC_EDGAR_CONTACT`).
It ships with a placeholder — replace it with any contact string of your
choosing (doesn't need to be your personal email) before running for real.

---

# Running it

```bash
cd paper_trading
pip install -r requirements.txt

python run_daily.py init          # one-time: creates the shared $130 account
python run_intel.py daily          # primary daily driver: the full intelligence sweep
python run_daily.py report         # plain paper-trading dashboard (works regardless of which engine traded)
```

`run_intel.py daily` and `run_daily.py run` **share the same account state
file and the same "already ran today" flag.** Run only one per day —
whichever runs first marks the day done and the other no-ops, rather than
risking two independent sets of trading decisions against the same $130
account on the same day.

### Testing

```bash
python -m pytest tests/ -v    # 68 tests, all offline/synthetic
```

### A note on network access in this sandbox

This code was developed and unit-tested inside an isolated cloud session
whose outbound network policy blocks Yahoo Finance, SEC EDGAR, and every
other market-data host tried directly (confirmed via `curl` — 403 at the
gateway). `WebSearch` (server-side, not routed through that proxy) *does*
work here, which is how `catalysts/macro_calendar_seed.py` was researched.
Everything else — `YFinanceProvider`, `SecEdgarProvider`,
`YFinanceOptionsProvider` — has **not** been exercised against live data
in this environment, only against synthetic `Fake*Provider` doubles in
`tests/`, which validate the exact same code paths (including a full
end-to-end scenario where a trade actually executes through the real
risk/broker-sim/portfolio/journal code) with deterministic data instead
of a live feed. Run both CLIs on a machine with normal internet access
for real data and real (paper) trades.

### Changelog
- 2026-08-17: Part A (single mechanical pullback strategy) built. No trades placed yet.
- 2026-08-18: Part B (market intelligence + convergence + paper trading) built on top,
  without modifying Part A. Found and fixed one real bug during testing: the
  accumulation/distribution trend calculation could falsely flag a perfectly flat
  price series as "ACCUMULATION" due to floating-point noise divided by a
  near-zero normalization floor — fixed to normalize against traded volume
  instead (see `intelligence/scanner.py` and the regression test in
  `tests/test_scanner.py`). Also tightened alert-level assignment so a
  ticker with zero independent evidence categories can never receive any
  alert level, regardless of baseline score components.
- 2026-08-18 (later same day): widened the scanner universe from 16 to
  ~465 tickers (small/mid-caps prioritized, per explicit request — early-
  footprint discovery is a primary objective and shouldn't be limited to
  famous names) via `intelligence/universe.py`. Added batched bar
  prefetching (`YFinanceProvider.prefetch_daily_bars`) and a two-stage
  scan-all/enrich-shortlist funnel (`scanner.is_notable`/`quick_score`,
  `SHORTLIST_MAX_FROM_WIDE`) so the wide universe stays computationally
  lightweight -- EDGAR/options calls are capped at the shortlist (≤56
  tickers/day), not run against all ~465. Found and fixed the same class
  of bug again in the new `quick_score()` heuristic (ordinary rel_volume
  ~1.0x was earning nonzero "notable" credit) before it shipped, caught
  by a dedicated test. 10 new tests (47 -> 57).
- 2026-08-18 (still later): added universe validation
  (`intelligence/universe_validation.py`) so the hand-compiled ticker
  list can be trusted over time -- ACTIVE/TEMPORARY_DATA_FAILURE/STALE/
  POSSIBLY_DELISTED/QUARANTINED/RENAMED_MERGED, escalating only after
  consecutive (never single-day) failures, zero extra network requests
  (piggybacks on the daily scan already happening), with quarantine
  reason+date logged and a separate opt-in `revalidate-quarantine`
  command for the small quarantined list. Also added `--diagnostics`
  reporting (scan failure count, pre-cap notable count, whether the
  shortlist cap bound, per-ticker promotion reasons) and runtime timing
  to `run_intel.py daily`, in preparation for the first real-data trial.
  11 new tests (57 -> 68).
