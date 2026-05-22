from __future__ import annotations

import re

from app.config import get_settings
from app.core.llm import chat
from app.core.types import ParsedClaim, RetrievedChunk


CLAIM_RE = re.compile(r"(?P<claim>.*?)(?:\s*\[(?P<source>[A-Z0-9_-]+)\])\s*$")


def draft_answer(
    question: str,
    retrieved_chunks: list[RetrievedChunk],
    temperature: float | None = None,
    model: str | None = None,
    byo_key: str | None = None,
) -> str:
    prompt = _build_prompt(question, retrieved_chunks)
    return chat(
        [
            {
                "role": "system",
                "content": (
                    "You are GlassBox, an auditable finance assistant. Answer only "
                    "from the provided sources. Every sentence must end with exactly "
                    "one [source_id] tag. If the sources do not support an answer, "
                    "say exactly INSUFFICIENT_CONTEXT."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature if temperature is not None else get_settings().llm_temperature,
        model=model,
        api_key=byo_key,
    )


def _build_prompt(question: str, retrieved_chunks: list[RetrievedChunk]) -> str:
    source_blocks = "\n".join(
        f"SOURCE {chunk.source_id} ({chunk.source_type}):\n{chunk.chunk_text}"
        for chunk in retrieved_chunks
    )
    return f"{source_blocks}\n\nQUESTION:\n{question}"


def parse_claims(draft: str, retrieved_chunks: list[RetrievedChunk]) -> list[ParsedClaim]:
    if draft.strip() == "INSUFFICIENT_CONTEXT":
        return []
    valid_sources = {chunk.source_id for chunk in retrieved_chunks}
    source_text_by_id = _source_text_by_id(retrieved_chunks)
    source_type_by_id = {chunk.source_id: chunk.source_type for chunk in retrieved_chunks}
    claims: list[ParsedClaim] = []
    for line in _claim_lines(draft):
        match = CLAIM_RE.match(line)
        if not match:
            continue
        source_id = match.group("source")
        claim_text = match.group("claim").strip()
        if not source_id or source_id not in valid_sources or not claim_text:
            continue
        claims.append(
            ParsedClaim(
                claim_text=claim_text,
                cited_source_id=source_id,
                source_text=source_text_by_id[source_id],
                source_type=source_type_by_id[source_id],
            )
        )
    return claims


def _claim_lines(draft: str) -> list[str]:
    lines: list[str] = []
    for raw_line in draft.splitlines():
        line = raw_line.strip().lstrip("-*0123456789. ")
        if line:
            lines.append(line)
    if len(lines) <= 1:
        return [part.strip() for part in re.split(r"(?<=\])\s+", draft.strip()) if part.strip()]
    return lines


def _source_text_by_id(retrieved_chunks: list[RetrievedChunk]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for chunk in retrieved_chunks:
        grouped.setdefault(chunk.source_id, []).append(chunk.chunk_text)
    return {source_id: "\n".join(texts) for source_id, texts in grouped.items()}
