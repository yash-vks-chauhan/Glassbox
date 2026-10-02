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

    if _asks_tax_guidance(question) or _asks_jurisdiction(question) or _asks_exception_process(question):
        return _compose_direct_answer(question, outcome, selected)

    if _asks_source_checklist(question):
        return _compose_source_checklist_answer(question, selected)

    if outcome == "flagged" or any(is_flagged_text(claim.claim_text) for claim in selected):
        return _compose_direct_answer(question, outcome, selected)

    if _asks_suitability(question):
        return _compose_suitability_answer(question, outcome, selected)

    return _compose_direct_answer(question, outcome, selected)


def _compose_direct_answer(question: str, outcome: str, claims: list[ParsedClaim]) -> str:
    lines = [_direct_line(question, outcome, claims), "Reason:"]
    lines.extend(_claim_line(claim) for claim in claims)
    action = _action_line(question, outcome, claims)
    if action:
        lines.append(action)
    return "\n".join(line for line in lines if line).strip()


def compose_refusal_reason(reason: str | None, *, question: str | None = None) -> str:
    base = (reason or "The approved document set does not support this request.").strip()
    if question:
        missing = _missing_source_hint(question)
        if missing and "missing source" not in base.lower():
            base = f"{base} Missing source: {missing}."
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
            return "No. Do not proceed as proposed."
        return "Needs review before client action."
    if _asks_exposure_permission(question) and any("exclusion" in claim.claim_text.lower() for claim in claims):
        return "The retrieved mandate does not show a cited restriction for the requested exposure."
    if _asks_conflicting_citation(question):
        return "Do not use the requested unrelated citation; use the subject fund factsheet evidence instead."
    if _asks_tax_guidance(question):
        return "Tax evidence handling:"
    if _asks_jurisdiction(question):
        return "Jurisdiction review:"
    if _asks_exception_process(question):
        return "Exception process:"
    if _asks_suitability(question):
        return _suitability_stance(claims)
    if re.match(r"^(can|may|would|should|is|are|does|do)\b", q):
        return "Yes, based on the approved sources."
    return "Here is the approved-source answer."


def _action_line(question: str, outcome: str, claims: list[ParsedClaim]) -> str:
    text = " ".join(claim.claim_text for claim in claims).lower()
    q = question.lower()
    if outcome == "flagged" or any(is_flagged_text(claim.claim_text) for claim in claims):
        if any(term in text for term in ["single-position", "single position", "allocation", "concentration"]) or re.search(
            r"\b(cap|limit|concentration|position)\b",
            q,
            re.I,
        ):
            return (
                "Action: reduce or restructure the trade before client action, "
                "or escalate to Compliance if an exception is requested."
            )
        if any(term in text for term in ["liquid", "liquidity"]):
            return (
                "Action: restore liquid assets to the cited floor before client action, "
                "or escalate to Compliance if an exception is requested."
            )
        if any(term in text for term in ["must not", "prohibited", "excluded", "restriction"]):
            return "Action: do not proceed unless Compliance approves an exception."
        return "Action: escalate to Compliance before taking client action."
    if _asks_tax_guidance(q):
        return "Action: cite the tax evidence policy and escalate to the Tax Desk before giving tax-rate advice."
    if _asks_jurisdiction(q):
        return "Action: cite the client IPS jurisdictions and escalate to Compliance for undocumented jurisdictions."
    if _asks_exception_process(q):
        return "Action: obtain documented Compliance approval before treating any IPS control as excepted."
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
    stance = _suitability_stance(claims)
    lines = [f"Suitability stance: {stance}", "Evidence:"]
    lines.extend(_claim_line(claim) for claim in claims)
    lines.append(_suitability_reason_line(claims))
    lines.append(_suitability_action_line(stance, claims))
    return "\n".join(line for line in lines if line).strip()


def _compose_source_checklist_answer(question: str, claims: list[ParsedClaim]) -> str:
    grouped = _group_claims_by_source_type(claims)
    lines = ["Source checklist before recommending:"]
    if grouped["ips"]:
        lines.append("Client IPS / mandate:")
        lines.extend(_source_checklist_claim_line(claim) for claim in grouped["ips"][:3])
    if grouped["portfolio"]:
        lines.append("Current portfolio snapshot:")
        lines.extend(_source_checklist_claim_line(claim) for claim in grouped["portfolio"][:2])
    if grouped["factsheet"]:
        lines.append("Fund factsheet:")
        lines.extend(_source_checklist_claim_line(claim) for claim in grouped["factsheet"][:4])
    if grouped["regulation"]:
        lines.append("Suitability guidance:")
        lines.extend(_source_checklist_claim_line(claim) for claim in grouped["regulation"][:2])
    lines.append(
        "Action: include the client IPS, current portfolio snapshot, fund factsheet, and suitability guidance in the advisory note before presenting the recommendation."
    )
    return "\n".join(lines).strip()


def _source_checklist_claim_line(claim: ParsedClaim) -> str:
    return f"- {_clean_sentence(claim.claim_text)} [{claim.cited_source_id}]"


def _asks_suitability(question: str) -> bool:
    q = question.lower()
    if _asks_source_checklist(question):
        return False
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
    ) or bool(
        re.search(r"\b(can|may|should|would)\b.*\b(buy|hold|invest|put|allocate|count|use|treat)\b.*\bF\d{3}\b", q, re.I)
        or re.search(r"\b(can|may|should|would)\b.*\bhold\b.*\bhigh-risk equity fund\b", q, re.I)
    )


def _asks_source_checklist(question: str) -> bool:
    return bool(
        re.search(r"\b(which|what)\s+sources?\b|\bsource checklist\b|\bwhat evidence\b", question, re.I)
        and re.search(r"\b(cite|cited|recommend|recommending|advisor|evidence)\b", question, re.I)
    )


def _asks_conflicting_citation(question: str) -> bool:
    return bool(re.search(r"\bcite\s+F\d{3}\b", question, re.I) and _primary_fund_ids(question))


def _asks_tax_guidance(question: str) -> bool:
    return bool(
        re.search(r"\b(tax|tax rate|capital gains|vat)\b", question, re.I)
        and re.search(
            r"\b(source|evidence|memo|approved|before|support|what should|do when|handling|cite|advisor)\b",
            question,
            re.I,
        )
    )


def _asks_jurisdiction(question: str) -> bool:
    return bool(
        re.search(r"\b(jurisdiction|jurisdictions|cross-border|country|countries)\b", question, re.I)
        and re.search(r"\b(C\d{3}|client|ips|constraint|govern|review|documented)\b", question, re.I)
    )


def _asks_exception_process(question: str) -> bool:
    return bool(re.search(r"\b(exception|verbally approves?|waiv\w*)\b", question, re.I))


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
    return concrete[:9 if _asks_source_checklist(question) else 6]


def _claim_relevant_to_question(question: str, claim: ParsedClaim) -> bool:
    q = question.lower()
    text = claim.claim_text.lower()
    primary_funds = _primary_fund_ids(question)
    if primary_funds and claim.source_type == "factsheet" and claim.cited_source_id not in primary_funds:
        return False
    if is_flagged_text(text) and not _flagged_claim_matches_question(q, text):
        return False
    asks_suitability = _asks_suitability(question) or any(term in q for term in ["suitable", "suitability", "recommend", "risk"])
    asks_fund_detail = any(term in q for term in ["factsheet", "sector", "invest", "asset class", "region"])
    asks_portfolio = any(term in q for term in ["current", "existing", "portfolio", "holding", "holdings", "exposure", "recommend"])
    if "risk profile" in text and not asks_suitability:
        return False
    if claim.source_type == "factsheet" and not (asks_suitability or asks_fund_detail):
        return False
    if claim.source_type == "portfolio" and not (asks_portfolio or asks_suitability):
        return False
    return True


def _asks_exposure_permission(question: str) -> bool:
    q = question.lower()
    return bool(
        any(term in q for term in ["tobacco", "firearms", "gambling", "cryptocurrency", "russia"])
        and re.search(r"\b(buy|invest|permit|exposure|mandate|allow|allowed)\b", q)
    )


def _flagged_claim_matches_question(question: str, claim_text: str) -> bool:
    restricted_terms = ["tobacco", "firearms", "gambling", "cryptocurrency", "russia"]
    asked_restrictions = [term for term in restricted_terms if term in question]
    if asked_restrictions:
        return any(term in claim_text for term in asked_restrictions)
    if re.search(r"\d+\s*%|\bpercent\b", question):
        return bool(
            re.search(
                r"\b(single[- ]position|position limit|allocation|concentration|portfolio value|exceed|violat|breach|liquid|liquidity)\b",
                claim_text,
                re.I,
            )
        )
    if any(term in question for term in ["suitable", "suitability", "recommend", "risk"]):
        return bool(re.search(r"\b(risk|suitab|recommend|profile|high|moderate|low)\b", claim_text, re.I))
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
    if is_flagged_text(text):
        return False
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
    if re.search(r"\b(violat|breach|cannot|can not|not allowed|not permitted|should not|must not|prohibited|excluded|restriction)\w*\b", text):
        severity = 0
    elif claim.source_type == "ips":
        severity = 1
    elif claim.source_type == "portfolio":
        severity = 2
    elif claim.source_type == "factsheet":
        severity = 3
    elif claim.source_type == "regulation":
        severity = 4
    else:
        severity = 5
    return (severity, len(claim.claim_text), claim.cited_source_id or "")


def _group_claims_by_source_type(claims: list[ParsedClaim]) -> dict[str, list[ParsedClaim]]:
    grouped = {"ips": [], "portfolio": [], "factsheet": [], "regulation": [], "other": []}
    for claim in claims:
        key = claim.source_type if claim.source_type in grouped else "other"
        grouped[key].append(claim)
    return grouped


def _suitability_stance(claims: list[ParsedClaim]) -> str:
    text = " ".join(claim.claim_text for claim in claims).lower()
    if any(is_flagged_text(claim.claim_text) for claim in claims):
        return "Not allowed under the cited mandate."
    if "high-risk equity funds require human review" in text:
        return "Review required before recommending."
    if "sector concentration risk" in text and re.search(r"\b(conservative|moderate)\b", text):
        return "Review required before recommending."
    if "high risk level" in text and re.search(r"\b(conservative|moderate)\b", text):
        return "Review required before recommending."
    if "may hold high-risk equity funds" in text:
        return "Potentially suitable if concentration and liquidity limits are satisfied."
    if "low risk level" in text:
        return "Evidence supports proceeding subject to mandate checks."
    return "Review required before recommending."


def _suitability_reason_line(claims: list[ParsedClaim]) -> str:
    text = " ".join(claim.claim_text for claim in claims).lower()
    if "high-risk equity funds require human review" in text:
        return "Why this matters: the client mandate requires human review for high-risk equity recommendations."
    if "sector concentration risk" in text:
        return "Why this matters: the product evidence raises sector concentration risk that must be checked against the client mandate."
    if "high risk level" in text and re.search(r"\b(conservative|moderate)\b", text):
        return "Why this matters: the fund risk level is higher than the client profile normally supports without review."
    if "may hold high-risk equity funds" in text:
        return "Why this matters: the mandate permits high-risk equity exposure only when concentration and liquidity conditions are satisfied."
    return "Why this matters: the recommendation must be consistent with the client mandate and product evidence."


def _suitability_action_line(stance: str, claims: list[ParsedClaim]) -> str:
    lowered = stance.lower()
    if lowered.startswith("not allowed"):
        return "Action: do not proceed unless Compliance approves an exception."
    if "review required" in lowered:
        return "Action: document the cited evidence and escalate to Compliance before presenting the recommendation."
    if "potentially suitable" in lowered:
        return "Action: confirm position size, liquidity, and exclusions before recommending."
    return "Action: document the cited evidence in the advisory note before recommending."


def _primary_fund_ids(question: str) -> set[str]:
    match = re.search(r"\bclaiming\s+(F\d{3})\b|\bas if\s+(F\d{3})\b", question, re.I)
    if not match:
        return set()
    return {item.upper() for item in match.groups() if item}


def _missing_source_hint(question: str) -> str | None:
    q = question.lower()
    if re.search(r"\b(tax|capital gains|vat)\b", q):
        return "approved tax guidance for the relevant jurisdiction"
    if re.search(r"\bF\d{3}\b", question, re.I):
        return "the requested fund factsheet"
    if re.search(r"\bC\d{3}\b", question, re.I):
        return "the requested client IPS"
    return None


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
