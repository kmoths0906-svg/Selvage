"""
Hand-researched macro calendar seed (spec §3, ECONOMIC section).

There is no free, structured, machine-readable API for the Fed/BLS
release calendar, so unlike everything else in this codebase, these
entries were populated by Claude via WebSearch against official sources
(federalreserve.gov, bls.gov) rather than fetched live by the running
program. That means this list goes STALE and needs a manual refresh --
it is not auto-updating. Check RESEARCHED_AS_OF before trusting it for
anything more than a few months out, and treat FOMC dates beyond the
next meeting as "tentative" per the Fed's own scheduling language.

To refresh: ask Claude to re-run the WebSearch queries and update this
file, or manually check federalreserve.gov/monetarypolicy/fomccalendars.htm
and bls.gov/schedule/.
"""

from __future__ import annotations

import datetime as dt

from .models import (
    Catalyst, IMPACT_HIGH, CERTAINTY_CONFIRMED, CERTAINTY_LIKELY,
)

RESEARCHED_AS_OF = dt.date(2026, 8, 18)

_FOMC_DECISION_MECHANISM = (
    "Rate decisions and forward guidance move yields, the dollar, and equity "
    "valuations broadly -- rate-sensitive sectors (tech, small caps, real estate) "
    "typically react hardest."
)
_ECON_RELEASE_MECHANISM = (
    "Surprises vs. consensus move rate expectations, which move yields, the "
    "dollar, and growth-stock valuations; can also move gold/oil via the "
    "inflation-expectations channel."
)


def _fomc(decision_date: dt.date, source: str) -> Catalyst:
    return Catalyst(
        date=decision_date, time_et="14:00 ET (decision), 14:30 ET (press conf.)",
        tickers=("SPY", "QQQ", "IWM"), category="FED",
        event="FOMC rate decision + press conference",
        significance="Federal Reserve interest-rate decision and forward guidance.",
        transmission_mechanism=_FOMC_DECISION_MECHANISM,
        source=source, impact=IMPACT_HIGH, certainty=CERTAINTY_LIKELY,
        retrieved_at=dt.datetime.combine(RESEARCHED_AS_OF, dt.time(0, 0), tzinfo=dt.timezone.utc),
    )


def _econ_release(release_date: dt.date, event: str, source: str) -> Catalyst:
    return Catalyst(
        date=release_date, time_et="08:30 ET", tickers=("SPY", "QQQ", "IWM"),
        category="ECONOMIC", event=event,
        significance=f"{event} -- a headline macro data release.",
        transmission_mechanism=_ECON_RELEASE_MECHANISM,
        source=source, impact=IMPACT_HIGH, certainty=CERTAINTY_CONFIRMED,
        retrieved_at=dt.datetime.combine(RESEARCHED_AS_OF, dt.time(0, 0), tzinfo=dt.timezone.utc),
    )


SEED_CATALYSTS: list[Catalyst] = [
    # FOMC 2026 schedule (decision/press-conference day only, i.e. day 2 of
    # each 2-day meeting). Fed's own release called this schedule
    # "tentative" -- treat dates as LIKELY, not CONFIRMED.
    # Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    # and https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm
    _fomc(dt.date(2026, 9, 16), "federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    _fomc(dt.date(2026, 10, 28), "federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    _fomc(dt.date(2026, 12, 9), "federalreserve.gov/monetarypolicy/fomccalendars.htm"),

    # Jobs report (Employment Situation) for August 2026 data.
    # Source: BLS schedule (via mass.gov 2026 data-release-schedule mirror).
    _econ_release(dt.date(2026, 9, 4), "Employment Situation (August 2026 data / jobs report)",
                  "bls.gov/schedule/ (mirrored: mass.gov/doc/2026-data-release-schedule)"),

    # PPI for August 2026 data.
    # Source: bls.gov/news.release/ppi.nr0.htm
    _econ_release(dt.date(2026, 9, 10), "Producer Price Index (August 2026 data)",
                  "bls.gov/news.release/ppi.nr0.htm"),

    # CPI for August 2026 data.
    # Source: bls.gov/cpi/
    _econ_release(dt.date(2026, 9, 11), "Consumer Price Index (August 2026 data)",
                  "bls.gov/cpi/"),
]
