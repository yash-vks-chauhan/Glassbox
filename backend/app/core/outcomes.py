from __future__ import annotations

import re

from app.core.types import ParsedClaim


FLAGGED_CLAIM_RE = re.compile(
    r"\b("
    r"violat(?:e|es|ed|ion)|"
    r"breach(?:es|ed)?|"
    r"cannot|"
    r"can not|"
    r"not allowed|"
    r"not permitted|"
    r"should not|"
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
    if text and re.search(r"recommendation should consider .*prohibited sector", text, re.I):
        return False
    return bool(text and FLAGGED_CLAIM_RE.search(text))
