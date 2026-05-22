from __future__ import annotations

import re
from collections import defaultdict

import httpx

from app.config import get_settings


class LLMUnavailable(RuntimeError):
    pass


def has_usable_openrouter_key(key: str | None) -> bool:
    normalized = (key or "").strip()
    if not normalized:
        return False
    placeholder_values = {
        "sk-or-...",
        "sk-or-your-key",
        "sk-or-your-key-here",
        "your-openrouter-key",
    }
    if normalized.lower() in placeholder_values:
        return False
    return normalized.startswith("sk-or-") and len(normalized) > 16


def chat(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    settings = get_settings()
    if settings.local_llm and not api_key:
        return _local_chat(messages)

    key = api_key or settings.openrouter_api_key
    if not has_usable_openrouter_key(key):
        raise LLMUnavailable("OPENROUTER_API_KEY is not configured")

    payload = {
        "model": model or settings.llm_model,
        "messages": messages,
        "temperature": temperature if temperature is not None else settings.llm_temperature,
    }
    try:
        with httpx.Client(timeout=45) as client:
            response = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "X-Title": "GlassBox",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise LLMUnavailable(str(exc)) from exc

    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable("OpenRouter returned an unexpected payload") from exc


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
    sources: dict[str, list[str]] = defaultdict(list)
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

    client_id = _id_in_question(question, "C") or _first_source_id(sources, prefix="C")
    fund_id = _id_in_question(question, "F") or _first_source_id(sources, prefix="F")
    claims: list[str] = []

    if "40%" in q or "40 percent" in q or "single position" in q:
        limit = _find_number_for_source(sources, client_id, r"exceed\s+(\d+)%")
        if client_id and limit is not None:
            proposed = _find_first_percent(question)
            if proposed is not None and proposed > limit:
                claims.append(
                    f"The proposed {proposed}% allocation violates Client {client_id}'s single-position limit because no single position may exceed {limit}% of portfolio value. [{client_id}]"
                )
            else:
                claims.append(
                    f"No single position may exceed {limit}% of portfolio value for Client {client_id}. [{client_id}]"
                )

    if any(term in q for term in ["suitable", "suitability", "risk"]):
        if fund_id and _contains_for_source(sources, fund_id, "high risk"):
            claims.append(f"Fund {fund_id} has a high risk level. [{fund_id}]")
        if client_id:
            profile = _risk_profile_for_source(sources, client_id)
            if profile:
                claims.append(f"Client {client_id} has a {profile} risk profile. [{client_id}]")
            if profile in {"conservative", "moderate"} and fund_id:
                claims.append(
                    f"A high-risk fund should be reviewed against Client {client_id}'s documented risk profile before recommendation. [REG-SUITABILITY]"
                )

    if any(term in q for term in ["tobacco", "firearms", "gambling", "russia"]):
        for source_id, texts in sources.items():
            source_text = " ".join(texts).lower()
            for term in ["tobacco", "firearms", "gambling", "russia"]:
                if term in q and term in source_text:
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


def _risk_profile_for_source(sources: dict[str, list[str]], source_id: str) -> str | None:
    text = " ".join(sources.get(source_id, [])).lower()
    for profile in ["conservative", "moderate", "aggressive"]:
        if profile in text:
            return profile
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
    if not re.search(r"\b(violate|violates|exceed|exceeds|above|greater)\b", claim, re.I):
        return False
    claim_values = [int(re.sub(r"\D", "", number)) for number in claim_numbers]
    source_values = [int(re.sub(r"\D", "", number)) for number in source_numbers]
    return bool(claim_values and source_values and max(claim_values) > min(source_values))
