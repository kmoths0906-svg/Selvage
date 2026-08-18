"""
SEC filing catalyst feed (spec §5 sources / §3 company events, the EDGAR
slice of it). Every catalyst produced here comes from an actual filed
legal document, so certainty is always CONFIRMED -- the filing exists,
full stop. What's uncertain is only how the market will react, which is
left to the significance/transmission_mechanism text, not the certainty
label.
"""

from __future__ import annotations

from . import config
from .data_providers import FORM_8K_ITEM_LABELS, FORM_TYPE_LABELS, EdgarProvider, Filing
from catalysts.models import Catalyst, CERTAINTY_CONFIRMED, IMPACT_LOW, IMPACT_MEDIUM, IMPACT_HIGH

# 8-K item code -> (impact, significance sentence, transmission mechanism)
_ITEM_IMPACT = {
    "1.01": (IMPACT_MEDIUM, "Entered a material agreement (contract/partnership/license/financing).",
             "New agreements can shift revenue expectations once terms become clear."),
    "1.02": (IMPACT_MEDIUM, "Terminated a material agreement.",
             "Loss of a material contract can pressure revenue expectations."),
    "1.03": (IMPACT_HIGH, "Bankruptcy or receivership filed.",
             "Existential risk to the equity; typically a severe, fast repricing event."),
    "2.01": (IMPACT_HIGH, "Completed an acquisition or disposition of assets.",
             "Changes the company's asset base/earnings power directly."),
    "2.02": (IMPACT_HIGH, "Reported results of operations / financial condition.",
             "Earnings-adjacent disclosure; historically one of the largest single-day movers."),
    "2.03": (IMPACT_MEDIUM, "Created a new direct financial obligation (debt).",
             "New leverage changes balance-sheet risk and interest expense."),
    "2.05": (IMPACT_MEDIUM, "Announced exit/disposal costs.",
             "Signals restructuring; can be read as either cost discipline or distress."),
    "3.02": (IMPACT_MEDIUM, "Unregistered sale of equity securities.",
             "Dilution risk -- new shares issued outside a registered offering."),
    "4.01": (IMPACT_MEDIUM, "Changed its certifying accountant.",
             "Auditor changes can (rarely) precede accounting concerns; usually administrative."),
    "5.01": (IMPACT_HIGH, "Change in control of the registrant.",
             "Ownership/control changes often precede major strategic shifts."),
    "5.02": (IMPACT_MEDIUM, "Departure or appointment of a director/officer.",
             "Leadership changes can signal strategic shifts or instability, direction unclear from the filing alone."),
    "5.03": (IMPACT_LOW, "Amended articles of incorporation or bylaws.",
             "Usually administrative."),
    "7.01": (IMPACT_LOW, "Regulation FD disclosure.",
             "Company chose to make information public to comply with fair-disclosure rules."),
    "8.01": (IMPACT_MEDIUM, "Disclosed other events (catch-all item).",
             "Content varies widely -- requires reading the actual filing to assess."),
    "9.01": (IMPACT_LOW, "Filed financial statements/exhibits.",
             "Usually accompanies another, more substantive item."),
}

_FORM_IMPACT = {
    "4": (IMPACT_MEDIUM, "Insider transaction filed (Form 4).",
          "Direction (buy/sell) and size require opening the filing; not assumed bullish or bearish here."),
    "S-1": (IMPACT_MEDIUM, "Registration statement filed -- potential new stock offering.",
            "New share issuance is a dilution risk if it proceeds."),
    "S-3": (IMPACT_MEDIUM, "Shelf registration filed -- potential future offering capacity.",
            "Company has registered the ability to issue more shares; dilution risk if drawn on."),
    "SC 13D": (IMPACT_HIGH, "Activist/control-oriented stake disclosed (13D).",
               "13D filers typically intend to influence the company -- historically associated with above-average volatility."),
    "SC 13G": (IMPACT_LOW, "Passive large stake disclosed (13G).",
               "Passive filers represent no stated intent to influence the company."),
}


def _classify_filing(f: Filing) -> tuple[str, str, str]:
    """Returns (impact, significance, transmission_mechanism)."""
    if f.form_type == "8-K" and f.items:
        # Use the highest-impact item present on this 8-K.
        order = {IMPACT_LOW: 0, IMPACT_MEDIUM: 1, IMPACT_HIGH: 2}
        best = max(f.items, key=lambda code: order.get(_ITEM_IMPACT.get(code, (IMPACT_LOW,))[0], 0))
        if best in _ITEM_IMPACT:
            impact, sig, mech = _ITEM_IMPACT[best]
            label = FORM_8K_ITEM_LABELS.get(best, f"Item {best}")
            return impact, f"8-K Item {best} ({label}): {sig}", mech
        return IMPACT_LOW, f"8-K filed with item(s) {', '.join(f.items)} (unmapped).", "Requires reading the filing."

    if f.form_type in _FORM_IMPACT:
        return _FORM_IMPACT[f.form_type]

    return IMPACT_LOW, f"{f.form_type} filed.", "Requires reading the filing to assess significance."


def build_edgar_catalysts(provider: EdgarProvider, tickers: list[str],
                           lookback_days: int = config.EDGAR_FILING_LOOKBACK_DAYS) -> list[Catalyst]:
    catalysts: list[Catalyst] = []
    for ticker in tickers:
        try:
            filings = provider.get_recent_filings(ticker, lookback_days)
        except Exception:
            continue  # DataUnavailableError -> simply no EDGAR catalysts for this ticker today

        for f in filings:
            impact, significance, mechanism = _classify_filing(f)
            catalysts.append(Catalyst(
                date=f.filed_date,
                time_et=None,
                tickers=(ticker,),
                category="SEC_FILING",
                event=f"{f.form_type} filed" + (f" (items {', '.join(f.items)})" if f.items else ""),
                significance=significance,
                transmission_mechanism=mechanism,
                source=f.primary_doc_url,
                impact=impact,
                certainty=CERTAINTY_CONFIRMED,
                retrieved_at=f.retrieved_at,
            ))
    return catalysts
