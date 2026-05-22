from __future__ import annotations

import re

from app.core.types import ParsedClaim


FLAGGED_CLAIM_RE = re.compile(
    r"\b("
    r"violat(?:e|es|ed|ion)|"
    r"breach(?:es|ed)?|"
    r"not permitted|"
    r"prohibited|"
    r"must not"
    r")\b",
    re.I,
)


def outcome_for_claims(claims: list[ParsedClaim]) -> str:
    if any(is_flagged_text(claim.claim_text) for claim in claims):
        return "flagged"
    return "answered"


def is_flagged_text(text: str | None) -> bool:
    return bool(text and FLAGGED_CLAIM_RE.search(text))
