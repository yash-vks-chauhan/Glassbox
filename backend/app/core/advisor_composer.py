from __future__ import annotations

import re

from app.core.outcomes import is_flagged_text
from app.core.types import ParsedClaim


def compose_advisor_answer(
    *,
    question: str,
    outcome: str,
    claims: list[ParsedClaim],
) -> str:
    """Render verified claims into an advisor-readable final answer.

    The model is allowed to draft source-cited claims earlier in the pipeline.
    This composer is deliberately deterministic and only uses claims that have
    already passed verification, so it can improve wording without introducing
    new finance facts.
    """

    selected = _select_claims(question, claims)
    if not selected:
        return ""

    if _asks_suitability(question):
        return _compose_suitability_answer(question, outcome, selected)

    lines = [_direct_line(question, outcome, selected), "Reason:"]
    lines.extend(_claim_line(claim) for claim in selected)
    action = _action_line(question, outcome, selected)
    if action:
        lines.append(action)
    return "\n".join(line for line in lines if line).strip()


def compose_refusal_reason(reason: str | None) -> str:
    base = (reason or "The approved document set does not support this request.").strip()
    if re.search(r"\b(action|escalate|compliance|human review)\b", base, re.I):
        return base
    return (
        f"{base} Action: escalate to Compliance before advising the client or "
        "expand the approved source set."
    )


def _direct_line(question: str, outcome: str, claims: list[ParsedClaim]) -> str:
    q = question.strip().lower()
    if outcome == "flagged" or any(is_flagged_text(claim.claim_text) for claim in claims):
        if re.match(r"^(can|may|would|should|is|are|does|do)\b", q):
            return "No. I would not proceed with this as proposed."
        return "Needs review before client action."
    if _asks_suitability(question):
        return "Needs review. The answer depends on the cited mandate and product evidence."
    if re.match(r"^(can|may|would|should|is|are|does|do)\b", q):
        return "Yes, based on the approved sources."
    return "Here is the approved-source answer."


def _action_line(question: str, outcome: str, claims: list[ParsedClaim]) -> str:
    text = " ".join(claim.claim_text for claim in claims).lower()
    q = question.lower()
    if outcome == "flagged" or any(is_flagged_text(claim.claim_text) for claim in claims):
        if any(term in text for term in ["single-position", "single position", "allocation", "concentration"]):
            return (
                "Action: reduce or restructure the trade before client action, "
                "or escalate to Compliance if an exception is requested."
            )
        if any(term in text for term in ["must not", "prohibited", "excluded", "restriction"]):
            return "Action: do not proceed unless Compliance approves an exception."
        return "Action: escalate to Compliance before taking client action."
    if _asks_suitability(q):
        return "Action: document the cited evidence in the advisory note before recommending."
    if any(term in q for term in ["limit", "cap", "maximum", "allocate", "allocation", "%", "percent"]):
        return "Action: use this cited limit when sizing the order."
    return "Action: use the cited sources in the client note."


def _compose_suitability_answer(
    question: str,
    outcome: str,
    claims: list[ParsedClaim],
) -> str:
    lines = [_direct_line(question, outcome, claims), "Evidence:"]
    lines.extend(_claim_line(claim) for claim in claims)
    lines.append(
        "Open checks: confirm client objective, liquidity need, concentration impact, "
        "and any missing product or suitability evidence before presenting this as a recommendation."
    )
    lines.append(
        "Action: document the cited evidence and escalate to Compliance if any required "
        "evidence is missing or the recommendation needs an exception."
    )
    return "\n".join(line for line in lines if line).strip()


def _asks_suitability(question: str) -> bool:
    q = question.lower()
    return any(
        term in q
        for term in [
            "suitable",
            "suitability",
            "recommend",
            "recommendation",
            "advise",
            "appropriate for",
        ]
    )


def _select_claims(question: str, claims: list[ParsedClaim]) -> list[ParsedClaim]:
    unique = _dedupe_claims([claim for claim in claims if claim.cited_source_id and claim.claim_text.strip()])
    if not unique:
        return []

    unique = [
        claim for claim in unique if _claim_relevant_to_question(question, claim)
    ]
    if not unique:
        unique = _dedupe_claims([claim for claim in claims if claim.cited_source_id and claim.claim_text.strip()])

    # Prefer concrete breach claims over generic mandate restatements. The
    # generic limit remains in the breach claim, so the advisor sees less noise.
    concrete = []
    for claim in unique:
        if _is_redundant_generic_limit(claim, unique):
            continue
        concrete.append(claim)

    concrete.sort(key=_claim_priority)
    return concrete[:6]


def _claim_relevant_to_question(question: str, claim: ParsedClaim) -> bool:
    q = question.lower()
    text = claim.claim_text.lower()
    if is_flagged_text(text):
        return True
    asks_suitability = any(term in q for term in ["suitable", "suitability", "recommend", "risk"])
    asks_fund_detail = any(term in q for term in ["factsheet", "sector", "invest", "asset class", "region"])
    if "risk profile" in text and not asks_suitability:
        return False
    if claim.source_type == "factsheet" and not (asks_suitability or asks_fund_detail):
        return False
    return True


def _dedupe_claims(claims: list[ParsedClaim]) -> list[ParsedClaim]:
    seen: set[tuple[str | None, str]] = set()
    deduped: list[ParsedClaim] = []
    for claim in claims:
        key = (claim.cited_source_id, _normalise_claim(claim.claim_text))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _is_redundant_generic_limit(claim: ParsedClaim, claims: list[ParsedClaim]) -> bool:
    text = claim.claim_text.lower()
    if "no single position may exceed" not in text:
        return False
    return any(
        other is not claim
        and other.cited_source_id == claim.cited_source_id
        and re.search(r"\b(violat|breach|exceed)\w*\b", other.claim_text, re.I)
        and _percent_set(claim.claim_text).issubset(_percent_set(other.claim_text))
        for other in claims
    )


def _claim_priority(claim: ParsedClaim) -> tuple[int, int, str]:
    text = claim.claim_text.lower()
    if re.search(r"\b(violat|breach|must not|prohibited|excluded|restriction)\w*\b", text):
        severity = 0
    elif claim.source_type == "ips":
        severity = 1
    elif claim.source_type == "factsheet":
        severity = 2
    elif claim.source_type == "regulation":
        severity = 3
    else:
        severity = 4
    return (severity, len(claim.claim_text), claim.cited_source_id or "")


def _claim_line(claim: ParsedClaim) -> str:
    return f"{_clean_sentence(claim.claim_text)} [{claim.cited_source_id}]"


def _clean_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"^(?:no|yes)\.\s+", "", cleaned, flags=re.I)
    if not re.search(r"[.!?]$", cleaned):
        cleaned += "."
    return cleaned


def _normalise_claim(text: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", text.lower()).strip()


def _percent_set(text: str) -> set[str]:
    return set(re.findall(r"\d+\s*%", text))
