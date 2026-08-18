"""Shared catalyst data model, used by both the EDGAR feed and the
14-day forward calendar so the two speak the same shape."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

IMPACT_LOW = "LOW_IMPACT"
IMPACT_MEDIUM = "MEDIUM_IMPACT"
IMPACT_HIGH = "HIGH_IMPACT"
IMPACT_BINARY = "BINARY_HIGH_RISK"

CERTAINTY_CONFIRMED = "CONFIRMED"
CERTAINTY_LIKELY = "LIKELY"
CERTAINTY_POSSIBLE = "POSSIBLE"
CERTAINTY_RUMOR = "RUMOR"
CERTAINTY_UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class Catalyst:
    date: dt.date
    time_et: Optional[str]          # e.g. "08:30 ET"; None if unknown/all-day
    tickers: tuple[str, ...]
    category: str                    # EARNINGS / ECONOMIC / SEC_FILING / FED / OTHER
    event: str
    significance: str                 # plain-English "why this could matter"
    transmission_mechanism: str        # plain-English "how it could move price"
    source: str
    impact: str
    certainty: str
    retrieved_at: Optional[dt.datetime] = None
