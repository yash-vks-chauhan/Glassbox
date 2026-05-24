from __future__ import annotations

from app.config import get_settings
from app.core.llm import chat
from app.core.trust_metrics import score_claim_support
from app.core.types import ParsedClaim


def verify_claims(
    claims: list[ParsedClaim],
    temperature: float | None = None,
    model: str | None = None,
    byo_key: str | None = None,
    enforce_production_gate: bool = True,
) -> tuple[list[ParsedClaim], list[ParsedClaim]]:
    kept: list[ParsedClaim] = []
    dropped: list[ParsedClaim] = []
    mode = get_settings().verify_mode.lower()
    min_support = get_settings().claim_min_grounding_score
    for claim in claims:
        source = claim.source_text or ""
        if not claim.cited_source_id or not source:
            dropped.append(
                ParsedClaim(
                    claim_text=claim.claim_text,
                    cited_source_id=claim.cited_source_id,
                    source_text=claim.source_text,
                    source_type=claim.source_type,
                    verified=False,
                    kept=False,
                    grounding_score=0.0,
                )
            )
            continue
        support_score = score_claim_support(claim.claim_text, source)
        if mode == "heuristic":
            supported_by_llm = support_score >= min_support
        elif mode == "llm":
            supported_by_llm = _llm_supports_claim(
                claim,
                source,
                temperature=temperature,
                model=model,
                byo_key=byo_key,
                enforce_production_gate=enforce_production_gate,
            )
        elif support_score >= 0.72:
            supported_by_llm = True
        elif support_score < min_support:
            supported_by_llm = False
        else:
            supported_by_llm = _llm_supports_claim(
                claim,
                source,
                temperature=temperature,
                model=model,
                byo_key=byo_key,
                enforce_production_gate=enforce_production_gate,
            )
        updated = ParsedClaim(
            claim_text=claim.claim_text,
            cited_source_id=claim.cited_source_id,
            source_text=claim.source_text,
            source_type=claim.source_type,
            verified=supported_by_llm,
            kept=supported_by_llm and support_score >= min_support,
            grounding_score=support_score,
        )
        if updated.kept:
            kept.append(updated)
        else:
            dropped.append(updated)
    return kept, dropped


def _llm_supports_claim(
    claim: ParsedClaim,
    source: str,
    *,
    temperature: float | None,
    model: str | None,
    byo_key: str | None,
    enforce_production_gate: bool,
) -> bool:
    verdict = chat(
        [
            {
                "role": "system",
                "content": (
                    "Answer only YES or NO. Do not explain. Verify whether the claim "
                    "is fully supported by the source text."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Is this claim fully supported by this source text?\n"
                    f"Claim:\n{claim.claim_text}\n"
                    f"Source:\n{source}"
                ),
            },
        ],
        temperature=temperature if temperature is not None else 0.0,
        model=model,
        api_key=byo_key,
        enforce_production_gate=enforce_production_gate,
    )
    return verdict.strip().upper().startswith("Y")
