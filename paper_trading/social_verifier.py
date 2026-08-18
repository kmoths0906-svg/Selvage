"""
Social-media claim verifier (spec §14).

There is no free, automatable API for TikTok/X/Reddit/YouTube/Discord at
any meaningful scale, so this is NOT an ambient scanner -- it's a
data model plus a documented workflow: you paste a claim/screenshot,
Claude works through the checklist below using WebSearch/WebFetch against
primary sources, and the structured result gets saved so it becomes part
of the learning database (did our own scanner independently find this
before the social post did?).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import learning_db

CLASSIFICATION_EARLY_SIGNAL = "EARLY_SIGNAL"
CLASSIFICATION_LEGITIMATE_ANALYSIS = "LEGITIMATE_ANALYSIS"
CLASSIFICATION_INTERESTING_UNPROVEN = "INTERESTING_BUT_UNPROVEN"
CLASSIFICATION_HINDSIGHT = "HINDSIGHT"
CLASSIFICATION_MISLEADING = "MISLEADING"
CLASSIFICATION_FALSE = "FALSE"

# The exact checklist Claude follows when asked to verify a claim (spec
# §14, steps 1-7). Kept here as the canonical process reference.
VERIFICATION_CHECKLIST = [
    "1. Extract the exact factual claim (strip out hype/interpretation).",
    "2. Independently verify it (WebSearch/WebFetch against primary sources).",
    "3. Find the original/primary source when possible (SEC filing, company PR, "
    "official transcript -- not a re-post of a re-post).",
    "4. Determine when the information became public (timestamp of the primary source).",
    "5. Determine whether the creator posted BEFORE or AFTER the meaningful price move.",
    "6. Separate facts (verifiable, sourced) from interpretation (the poster's opinion).",
    "7. Determine whether our own scanner (intelligence/scanner.py, edgar.py, "
    "options_lite.py) could plausibly have found this independently, and if so, when.",
]


@dataclass
class SocialClaim:
    platform: str
    claim_text: str
    ticker: Optional[str] = None
    posted_at: Optional[dt.datetime] = None
    url: Optional[str] = None


@dataclass
class VerificationResult:
    claim: SocialClaim
    facts: list[str]
    interpretation: list[str]
    primary_sources: list[str]
    info_public_since: Optional[dt.datetime]
    posted_before_move: Optional[bool]
    scanner_would_have_found: Optional[bool]
    scanner_found_explanation: str
    classification: str
    notes: str


def save_verification(conn, result: VerificationResult) -> None:
    learning_db.record_social_verification(
        conn,
        claim_text=result.claim.claim_text,
        ticker=result.claim.ticker,
        source_platform=result.claim.platform,
        claim_public_at=result.claim.posted_at.isoformat() if result.claim.posted_at else None,
        classification=result.classification,
        scanner_would_have_found=result.scanner_would_have_found,
        notes=result.notes,
    )
