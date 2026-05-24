from __future__ import annotations

import re
from collections import defaultdict

from app.config import get_settings
from app.core.model_router import (
    LLMUnavailable,
    chat_with_router,
    has_usable_openrouter_key,
)


def chat(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    model: str | None = None,
    api_key: str | None = None,
    enforce_production_gate: bool = True,
) -> str:
    return chat_with_router(
        messages,
        local_chat=_local_chat,
        temperature=temperature if temperature is not None else get_settings().llm_temperature,
        model=model,
        api_key=api_key,
        enforce_production_gate=enforce_production_gate,
    )


def _local_chat(messages: list[dict[str, str]]) -> str:
    combined = "\n".join(message.get("content", "") for message in messages)
    if "Is this claim fully supported by this source text?" in combined:
        claim = _extract_block(combined, "Claim")
        source = _extract_block(combined, "Source")
        return "YES" if _supported(claim, source) else "NO"
    return _local_answer(combined)


def _extract_block(text: str, label: str) -> str:
    pattern = rf"{label}:\s*(.*?)(?:\n[A-Z][A-Za-z ]+:\s*|\Z)"
    match = re.search(pattern, text, flags=re.S)
    return match.group(1).strip() if match else ""


def _source_map(prompt: str) -> dict[str, list[str]]:
    """Parse the source blocks out of an answer-agent prompt.

    Phase E switched the wire format from ``SOURCE X (type):`` plain text
    headers to ``<source id="X" type="...">...</source>`` XML-style
    wrappers (prompt-injection containment). We accept both shapes here so
    the deterministic local LLM keeps working when other tests use older
    fixtures and so any in-flight prompt cache lines remain parseable.
    """
    sources: dict[str, list[str]] = defaultdict(list)
    # Phase E shape: <source id="X" type="..."> ... </source>
    for match in re.finditer(
        r'<source\s+id="([A-Z0-9_-]+)"\s+type="([^"]+)"\s*>\s*(.*?)\s*</source>',
        prompt,
        flags=re.S | re.I,
    ):
        source_id = match.group(1)
        text = " ".join(line.strip() for line in match.group(3).splitlines() if line.strip())
        if text:
            sources[source_id].append(text)
    if sources:
        return sources
    # Legacy shape (Phase D and earlier).
    for match in re.finditer(
        r"SOURCE\s+([A-Z0-9_-]+)\s+\(([^)]+)\):\s*(.*?)(?=\nSOURCE\s+[A-Z0-9_-]+\s+\(|\nQUESTION:|\Z)",
        prompt,
        flags=re.S,
    ):
        source_id = match.group(1)
        text = " ".join(line.strip() for line in match.group(3).splitlines() if line.strip())
        if text:
            sources[source_id].append(text)
    return sources


def _local_answer(prompt: str) -> str:
    question = _extract_block(prompt, "QUESTION") or prompt
    q = question.lower()
    sources = _source_map(prompt)
    all_text = " ".join(" ".join(parts) for parts in sources.values()).lower()

    if any(term in q for term in ["capital gains", "tax rate", "germany tax"]):
        if "capital gains" not in all_text and "tax rate" not in all_text:
            return "INSUFFICIENT_CONTEXT"

    question_client_id = _id_in_question(question, "C")
    client_id = question_client_id if question_client_id in sources else _first_source_id(sources, prefix="C")
    claimed_fund_id = _claimed_fund_id(question)
    question_fund_id = claimed_fund_id or _id_in_question(question, "F")
    fund_id = question_fund_id if question_fund_id in sources else _first_source_id(sources, prefix="F")
    claims: list[str] = []

    if any(
        term in q
        for term in [
            "40%",
            "40 percent",
            "single position",
            "concentration",
            "position",
            "one fund",
            "maximum",
            "cap",
            "allocate",
            "allocation",
        ]
    ):
        limit = _find_number_for_source(sources, client_id, r"exceed\s+(\d+)%")
        if client_id and limit is not None:
            proposed = _find_first_percent(question)
            if "ignore" in q and "cap" in q:
                claims.append(
                    f"Ignoring the {limit}% concentration cap would breach Client {client_id}'s single-position limit. [{client_id}]"
                )
            elif proposed is not None and proposed > limit:
                claims.append(
                    f"The proposed {proposed}% allocation violates Client {client_id}'s single-position limit because no single position may exceed {limit}% of portfolio value. [{client_id}]"
                )
            else:
                claims.append(
                    f"No single position may exceed {limit}% of portfolio value for Client {client_id}. [{client_id}]"
                )

    if any(term in q for term in ["suitable", "suitability", "risk", "recommend", "recommendation"]):
        fund_risk = _risk_level_for_source(sources, fund_id) if fund_id else None
        if fund_id and fund_risk:
            claims.append(f"Fund {fund_id} has a {fund_risk} risk level. [{fund_id}]")
            if "technology" in " ".join(sources.get(fund_id, [])).lower():
                sentence = _sentence_for_term(" ".join(sources[fund_id]), "technology")
                if sentence:
                    claims.append(f"{sentence}. [{fund_id}]")
        if client_id:
            profile = _risk_profile_for_source(sources, client_id)
            if profile:
                claims.append(f"Client {client_id} has a {profile} risk profile. [{client_id}]")
            elif "recommend" in q:
                sentence = _sentence_for_term(" ".join(sources.get(client_id, [])), client_id)
                if sentence:
                    claims.append(f"{sentence}. [{client_id}]")
            if "REG-SUITABILITY" in sources and (
                "recommend" in q or (profile in {"conservative", "moderate"} and fund_risk == "high")
            ):
                sentence = _sentence_for_term(" ".join(sources["REG-SUITABILITY"]), "recommendation")
                if sentence:
                    claims.append(f"{sentence}. [REG-SUITABILITY]")

    if fund_id and any(term in q for term in ["claiming", "government bond", "as if"]):
        fund_risk = _risk_level_for_source(sources, fund_id)
        if fund_risk:
            claims.append(f"Fund {fund_id} has a {fund_risk} risk level. [{fund_id}]")
        if "technology" in " ".join(sources.get(fund_id, [])).lower():
            sentence = _sentence_for_term(" ".join(sources[fund_id]), "technology")
            if sentence:
                claims.append(f"{sentence}. [{fund_id}]")

    if "REG-SUITABILITY" in sources and any(
        term in q for term in ["escalate", "available documents", "concentration", "liquidity", "prohibited sector"]
    ):
        term = "human" if "escalate" in q or "available documents" in q else "concentration"
        if "liquidity" in q:
            term = "liquidity"
        if "prohibited sector" in q:
            term = "prohibited sector"
        reg_text = " ".join(sources["REG-SUITABILITY"])
        sentence = _sentence_for_term(reg_text, term) or _first_sentence(reg_text)
        if sentence:
            claims.append(f"{sentence}. [REG-SUITABILITY]")

    if any(term in q for term in ["tobacco", "firearms", "gambling", "russia", "cryptocurrency"]):
        for source_id, texts in sources.items():
            source_text = " ".join(texts).lower()
            for term in ["tobacco", "firearms", "gambling", "russia", "cryptocurrency"]:
                if term in q and term in source_text:
                    sentence = _sentence_for_term(" ".join(texts), term)
                    if sentence:
                        claims.append(f"{sentence}. [{source_id}]")
                    else:
                        claims.append(f"Client {source_id} has a restriction involving {term}. [{source_id}]")

    if not claims:
        for source_id, texts in list(sources.items())[:3]:
            sentence = texts[0].split(".")[0].strip()
            if sentence:
                claims.append(f"{sentence}. [{source_id}]")

    return "\n".join(dict.fromkeys(claims)) if claims else "INSUFFICIENT_CONTEXT"


def _first_source_id(sources: dict[str, list[str]], prefix: str) -> str | None:
    for source_id in sources:
        if source_id.startswith(prefix):
            return source_id
    return None


def _id_in_question(question: str, prefix: str) -> str | None:
    match = re.search(rf"\b({prefix}\d{{3}})\b", question, flags=re.I)
    return match.group(1).upper() if match else None


def _claimed_fund_id(question: str) -> str | None:
    match = re.search(r"\bclaiming\s+(F\d{3})\b", question, flags=re.I)
    return match.group(1).upper() if match else None


def _find_number_for_source(
    sources: dict[str, list[str]], source_id: str | None, pattern: str
) -> int | None:
    if not source_id:
        return None
    match = re.search(pattern, " ".join(sources.get(source_id, [])), flags=re.I)
    return int(match.group(1)) if match else None


def _find_first_percent(text: str) -> int | None:
    match = re.search(r"(\d+)\s*%", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s+percent", text, flags=re.I)
    return int(match.group(1)) if match else None


def _contains_for_source(sources: dict[str, list[str]], source_id: str, needle: str) -> bool:
    return needle.lower() in " ".join(sources.get(source_id, [])).lower()


def _sentence_for_term(text: str, term: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        cleaned = sentence.strip().rstrip(".")
        if term.lower() in cleaned.lower():
            return cleaned
    return None


def _first_sentence(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        cleaned = sentence.strip().rstrip(".")
        if cleaned:
            return cleaned
    return None


def _risk_profile_for_source(sources: dict[str, list[str]], source_id: str) -> str | None:
    text = " ".join(sources.get(source_id, [])).lower()
    for profile in ["conservative", "moderate", "aggressive"]:
        if profile in text:
            return profile
    return None


def _risk_level_for_source(sources: dict[str, list[str]], source_id: str | None) -> str | None:
    if not source_id:
        return None
    text = " ".join(sources.get(source_id, [])).lower()
    for level in ["low", "moderate", "high"]:
        if f"{level} risk" in text or f"{level} risk level" in text:
            return level
    return None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9%_]+", text.lower()))


def _supported(claim: str, source: str) -> bool:
    if not claim or not source:
        return False
    claim_numbers = set(re.findall(r"\d+%?", claim))
    source_numbers = set(re.findall(r"\d+%?", source))
    if claim_numbers and not claim_numbers.issubset(source_numbers):
        if not _supported_numeric_inference(claim, claim_numbers, source_numbers):
            return False
    claim_tokens = _tokens(claim) - {"the", "a", "an", "is", "has", "have", "because", "client", "fund"}
    source_tokens = _tokens(source)
    if not claim_tokens:
        return False
    overlap = len(claim_tokens & source_tokens) / len(claim_tokens)
    return overlap >= 0.45


def _supported_numeric_inference(
    claim: str, claim_numbers: set[str], source_numbers: set[str]
) -> bool:
    if not source_numbers:
        return False
    if not re.search(
        r"\b(violate|violates|breach|breaches|exceed|exceeds|above|greater|cannot|can not|not allowed|not permitted)\b",
        claim,
        re.I,
    ):
        return False
    claim_values = [int(re.sub(r"\D", "", number)) for number in claim_numbers]
    source_values = [int(re.sub(r"\D", "", number)) for number in source_numbers]
    if claim_values and source_values and max(claim_values) > min(source_values):
        return True
    if claim_values and source_values and re.search(r"\b(at least|floor|below|liquidity)\b", claim, re.I):
        return min(claim_values) < max(source_values)
    return False
