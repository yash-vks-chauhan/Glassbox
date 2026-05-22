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
) -> tuple[list[ParsedClaim], list[ParsedClaim]]:
    kept: list[ParsedClaim] = []
    dropped: list[ParsedClaim] = []
    for claim in claims:
        source = claim.source_text or ""
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
            temperature=temperature if temperature is not None else get_settings().llm_temperature,
            model=model,
            api_key=byo_key,
        )
        supported_by_llm = verdict.strip().upper().startswith("Y")
        support_score = score_claim_support(claim.claim_text, source)
        updated = ParsedClaim(
            claim_text=claim.claim_text,
            cited_source_id=claim.cited_source_id,
            source_text=claim.source_text,
            source_type=claim.source_type,
            verified=supported_by_llm,
            kept=supported_by_llm and support_score >= 0.45,
            grounding_score=support_score,
        )
        if updated.kept:
            kept.append(updated)
        else:
            dropped.append(updated)
    return kept, dropped
