from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    client_id: str | None = None
    byo_key: str | None = None


class Citation(BaseModel):
    source_id: str
    source_type: str
    snippet: str


class Trust(BaseModel):
    grounding_score: float | None = None
    determinism_score: float | None = None


class AskResponse(BaseModel):
    decision_id: str
    outcome: str
    answer: str | None = None
    citations: list[Citation] = []
    refusal_reason: str | None = None
    trust: Trust = Trust()


class RetrievedChunkOut(BaseModel):
    source_id: str
    source_type: str
    chunk_text: str
    score: float


class ClaimOut(BaseModel):
    claim_text: str
    cited_source_id: str | None = None
    verified: bool = False
    kept: bool = False


class AuditSummary(BaseModel):
    id: str
    created_at: str
    question: str
    client_id: str | None
    outcome: str
    grounding_score: float | None
    determinism_score: float | None
    latency_ms: int


class AuditDetail(AuditSummary):
    final_answer: str | None
    retrieved_chunks: list[RetrievedChunkOut]
    decision_claims: list[ClaimOut]


class MetricsSummary(BaseModel):
    total: int
    hallucination_rate: float
    refusal_rate: float
    flagged_rate: float
    avg_determinism: float | None
    audit_completeness: float


class DeterminismRequest(BaseModel):
    question: str = Field(min_length=3)
    client_id: str | None = None
    runs: int | None = Field(default=None, ge=2, le=10)
    alternate_model: str | None = None


class DeterminismResponse(BaseModel):
    determinism_score: float
    representative_decision_id: str | None
    per_run_outcomes: list[AskResponse]
