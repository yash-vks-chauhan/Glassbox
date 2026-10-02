from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.retrieval import evidence_quality
from app.core.types import RetrievedChunk


@dataclass(frozen=True)
class AnswerabilityDecision:
    answerable: bool
    reason: str
    required_sources: tuple[str, ...]
    evidence_quality: float


def assess_answerability(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> AnswerabilityDecision:
    source_ids = {chunk.source_id for chunk in retrieved}
    required = _required_sources(question, client_id)
    missing = [source_id for source_id in required if source_id not in source_ids]
    quality = evidence_quality(retrieved)
    if missing:
        return AnswerabilityDecision(
            answerable=False,
            reason="Missing required evidence source(s): " + ", ".join(missing),
            required_sources=tuple(required),
            evidence_quality=quality,
        )
    if quality < 0.18:
        return AnswerabilityDecision(
            answerable=False,
            reason=f"Evidence quality {quality:.2f} is below the product answerability threshold.",
            required_sources=tuple(required),
            evidence_quality=quality,
        )
    return AnswerabilityDecision(
        answerable=True,
        reason="Required evidence is present.",
        required_sources=tuple(required),
        evidence_quality=quality,
    )


def _required_sources(question: str, client_id: str | None) -> list[str]:
    q = question.lower()
    required: list[str] = []
    mentioned_client = client_id or _client_id(question)
    mentioned_funds = _fund_ids(question)
    asks_mandate = any(
        term in q
        for term in [
            "mandate",
            "ips",
            "single position",
            "concentration",
            "liquid",
            "liquidity",
            "risk profile",
            "exclude",
            "excluded",
            "permit",
            "exposure",
            "allocate",
            "allocation",
            "jurisdiction",
            "cross-border",
            "%",
            "percent",
        ]
    )
    asks_suitability = any(term in q for term in ["suitable", "suitability", "recommend", "recommending"]) or _asks_fund_transaction(q)
    asks_risk_guidance = (
        ("risk" in q and "sector" in q)
        or ("risk" in q and "concentration" in q)
    )
    if mentioned_client and (asks_mandate or asks_suitability):
        required.append(mentioned_client)
    if _needs_portfolio_source(question, mentioned_client):
        required.append(_portfolio_source_id(mentioned_client))
    if mentioned_funds:
        required.extend(mentioned_funds)
    if asks_suitability or asks_risk_guidance:
        required.append("REG-SUITABILITY")
    if _asks_tax_guidance(question):
        required.append("REG-TAX-GUIDANCE")
    if _asks_jurisdiction(question):
        if mentioned_client:
            required.append(mentioned_client)
        required.append("REG-JURISDICTION")
    if re.search(r"\b(exception|verbally approves?|waiv\w*)\b", q):
        required.append("REG-EXCEPTIONS")
    return list(dict.fromkeys(required))


def _client_id(question: str) -> str | None:
    match = re.search(r"\b(C\d{3})\b", question, flags=re.I)
    return match.group(1).upper() if match else None


def _fund_ids(question: str) -> list[str]:
    return list(dict.fromkeys(match.upper() for match in re.findall(r"\bF\d{3}\b", question, flags=re.I)))


def _portfolio_source_id(client_id: str | None) -> str:
    return f"PORTFOLIO-{client_id}" if client_id else ""


def _asks_fund_transaction(question: str) -> bool:
    return bool(
        re.search(r"\b(can|may|should|would)\b", question, re.I)
        and re.search(r"\b(buy|hold|invest|put|allocate|count|use|treat)\b", question, re.I)
        and re.search(r"\bF\d{3}\b|\bhigh-risk equity fund\b", question, re.I)
    )


def _asks_tax_guidance(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(r"\b(tax|tax rate|capital gains|vat)\b", q)
        and re.search(
            r"\b(source|evidence|memo|approved|before|support|what should|do when|handling|cite|advisor)\b",
            q,
        )
    )


def _asks_jurisdiction(question: str) -> bool:
    return bool(
        re.search(r"\b(jurisdiction|jurisdictions|cross-border|country|countries)\b", question, re.I)
        and re.search(r"\b(C\d{3}|client|ips|constraint|govern|review|documented)\b", question, re.I)
    )


def _needs_portfolio_source(question: str, client_id: str | None) -> bool:
    if not client_id:
        return False
    q = question.lower()
    return bool(
        re.search(
            r"\b(current|existing|portfolio|holding|holdings|post[- ]trade|after|before recommending|recommend\w*|add|breach\w*)\b",
            q,
        )
        and re.search(
            r"\b(client|C\d{3}|technology|sector|liquid|liquidity|F\d{3}|suitable|recommend\w*)\b",
            question,
            re.I,
        )
    )
