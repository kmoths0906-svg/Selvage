"""
Data providers for the intelligence layer that aren't plain OHLCV bars:
SEC EDGAR filings and options-chain snapshots. Kept out of
papertrader/data_source.py deliberately -- that module's contract is
"price bars and quotes," this is a different shape of data with its own
failure modes, and keeping them separate means either can be swapped or
disabled independently.

Every function here either returns real data with its source, or raises
DataUnavailableError. Nothing is fabricated.
"""

from __future__ import annotations

import abc
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from papertrader.data_source import DataUnavailableError
from . import config


# ============================= SEC EDGAR ================================

@dataclass(frozen=True)
class Filing:
    ticker: str
    cik: str
    form_type: str
    filed_date: dt.date
    accession_number: str
    primary_doc_url: str
    items: tuple[str, ...]        # 8-K item codes, e.g. ("1.01", "9.01"); empty for other forms
    source: str = "SEC EDGAR"
    retrieved_at: Optional[dt.datetime] = None


# 8-K item code -> human label. Not exhaustive; unmapped codes still show
# with their raw code rather than being silently dropped.
FORM_8K_ITEM_LABELS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "3.02": "Unregistered Sales of Equity Securities",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

FORM_TYPE_LABELS = {
    "4": "Insider transaction (Form 4)",
    "S-1": "Registration statement / potential new offering (S-1)",
    "S-3": "Shelf registration / potential offering (S-3)",
    "SC 13D": "Activist/control stake disclosure (13D)",
    "SC 13G": "Passive large stake disclosure (13G)",
}


class EdgarProvider(abc.ABC):
    @abc.abstractmethod
    def get_recent_filings(self, ticker: str, lookback_days: int) -> list[Filing]:
        """Return filings for `ticker` filed within the last `lookback_days`."""


class SecEdgarProvider(EdgarProvider):
    """Free, official, no API key. Requires a descriptive User-Agent per
    SEC's automated-access policy (config.SEC_EDGAR_CONTACT)."""

    TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

    def __init__(self, cache_path: Optional[Path] = None):
        import requests
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": config.SEC_EDGAR_CONTACT})
        self._cache_path = cache_path or (config.INTEL_DIR / "data" / "edgar_ticker_cik_cache.json")
        self._ticker_to_cik: Optional[dict[str, str]] = None

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik

        if self._cache_path.exists():
            try:
                raw = json.loads(self._cache_path.read_text())
                self._ticker_to_cik = raw
                return raw
            except (json.JSONDecodeError, OSError):
                pass

        resp = self._session.get(self.TICKER_MAP_URL, timeout=15)
        if resp.status_code != 200:
            raise DataUnavailableError(f"EDGAR ticker map fetch failed: HTTP {resp.status_code}")
        raw = resp.json()
        mapping = {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in raw.values()}

        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(mapping))
        self._ticker_to_cik = mapping
        return mapping

    def get_recent_filings(self, ticker: str, lookback_days: int) -> list[Filing]:
        ticker_map = self._load_ticker_map()
        cik = ticker_map.get(ticker.upper())
        if cik is None:
            raise DataUnavailableError(f"No CIK found for ticker {ticker!r} in EDGAR ticker map")

        url = self.SUBMISSIONS_URL.format(cik10=cik)
        resp = self._session.get(url, timeout=15)
        if resp.status_code != 200:
            raise DataUnavailableError(f"EDGAR submissions fetch failed for {ticker}: HTTP {resp.status_code}")
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        items_raw = recent.get("items", [""] * len(forms))
        primary_docs = recent.get("primaryDocument", [""] * len(forms))

        cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
        retrieved_at = dt.datetime.now(tz=dt.timezone.utc)

        results = []
        for i in range(len(forms)):
            form = forms[i]
            if form not in config.EDGAR_FORM_TYPES_OF_INTEREST:
                continue
            filed = dt.date.fromisoformat(dates[i])
            if filed < cutoff:
                continue
            accession_nodash = accessions[i].replace("-", "")
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_nodash}/{primary_docs[i]}"
            )
            items = tuple(x for x in items_raw[i].split(",") if x) if items_raw[i] else ()
            results.append(Filing(
                ticker=ticker.upper(),
                cik=cik,
                form_type=form,
                filed_date=filed,
                accession_number=accessions[i],
                primary_doc_url=doc_url,
                items=items,
                retrieved_at=retrieved_at,
            ))
        return results


class FakeEdgarProvider(EdgarProvider):
    """Deterministic offline double for tests. Filters relative to an
    explicit `reference_date` rather than the real wall clock, so tests
    (including retrospective ones pinned to a past date) stay correct
    regardless of what day they actually run on."""

    def __init__(self, filings_by_ticker: dict[str, list[Filing]], reference_date: Optional[dt.date] = None):
        self._filings = filings_by_ticker
        self._reference_date = reference_date or dt.date.today()

    def get_recent_filings(self, ticker: str, lookback_days: int) -> list[Filing]:
        cutoff = self._reference_date - dt.timedelta(days=lookback_days)
        return [f for f in self._filings.get(ticker.upper(), []) if f.filed_date >= cutoff]


# ============================= OPTIONS ================================

@dataclass(frozen=True)
class OptionContract:
    ticker: str
    expiration: str          # ISO date string
    strike: float
    contract_type: str       # "call" or "put"
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: float


@dataclass(frozen=True)
class OptionChain:
    ticker: str
    expiration: str
    underlying_price: float
    calls: tuple[OptionContract, ...]
    puts: tuple[OptionContract, ...]
    retrieved_at: dt.datetime


class OptionsDataProvider(abc.ABC):
    @abc.abstractmethod
    def get_nearest_expirations(self, ticker: str, count: int) -> list[str]:
        """Return up to `count` upcoming expiration date strings (ISO)."""

    @abc.abstractmethod
    def get_option_chain(self, ticker: str, expiration: str) -> OptionChain:
        """Return the full chain for one expiration."""


class YFinanceOptionsProvider(OptionsDataProvider):
    """Free, no key. A point-in-time snapshot only (volume/OI/IV as of the
    fetch) -- NOT time-and-sales, so it cannot show sweeps, aggressor
    side, or intraday flow. See intelligence/options_lite.py for how this
    limitation is handled in scoring."""

    def __init__(self) -> None:
        import yfinance as yf
        self._yf = yf

    def get_nearest_expirations(self, ticker: str, count: int) -> list[str]:
        t = self._yf.Ticker(ticker)
        try:
            exps = list(t.options)
        except Exception as e:
            raise DataUnavailableError(f"No options expirations for {ticker!r}: {e}")
        if not exps:
            raise DataUnavailableError(f"No listed options found for {ticker!r}")
        return exps[:count]

    def get_option_chain(self, ticker: str, expiration: str) -> OptionChain:
        t = self._yf.Ticker(ticker)
        try:
            chain = t.option_chain(expiration)
        except Exception as e:
            raise DataUnavailableError(f"Option chain fetch failed for {ticker!r} {expiration}: {e}")

        try:
            underlying_price = float(t.fast_info.get("last_price"))
        except Exception:
            underlying_price = float("nan")

        now = dt.datetime.now(tz=dt.timezone.utc)

        def _rows(df, contract_type):
            out = []
            for _, r in df.iterrows():
                out.append(OptionContract(
                    ticker=ticker,
                    expiration=expiration,
                    strike=float(r["strike"]),
                    contract_type=contract_type,
                    last_price=float(r.get("lastPrice", float("nan"))),
                    bid=float(r.get("bid", float("nan"))),
                    ask=float(r.get("ask", float("nan"))),
                    volume=int(r["volume"]) if r.get("volume") == r.get("volume") else 0,
                    open_interest=int(r["openInterest"]) if r.get("openInterest") == r.get("openInterest") else 0,
                    implied_volatility=float(r.get("impliedVolatility", float("nan"))),
                ))
            return out

        return OptionChain(
            ticker=ticker,
            expiration=expiration,
            underlying_price=underlying_price,
            calls=tuple(_rows(chain.calls, "call")),
            puts=tuple(_rows(chain.puts, "put")),
            retrieved_at=now,
        )


class FakeOptionsProvider(OptionsDataProvider):
    def __init__(self, chains: dict[tuple[str, str], OptionChain]):
        self._chains = chains

    def get_nearest_expirations(self, ticker: str, count: int) -> list[str]:
        exps = sorted({exp for (t, exp) in self._chains if t == ticker})
        if not exps:
            raise DataUnavailableError(f"No fake expirations set up for {ticker!r}")
        return exps[:count]

    def get_option_chain(self, ticker: str, expiration: str) -> OptionChain:
        key = (ticker, expiration)
        if key not in self._chains:
            raise DataUnavailableError(f"No fake chain set up for {key}")
        return self._chains[key]
