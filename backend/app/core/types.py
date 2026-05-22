from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    source_type: str
    chunk_text: str
    score: float
    file: str | None = None
    chunk_index: int | None = None


@dataclass(frozen=True)
class ParsedClaim:
    claim_text: str
    cited_source_id: str | None
    source_text: str | None = None
    source_type: str | None = None
    verified: bool = False
    kept: bool = False
    grounding_score: float | None = None
