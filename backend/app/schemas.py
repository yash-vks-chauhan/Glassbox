import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator


# Phase D path-traversal guard. Any user-supplied identifier that ends up being
# matched against the corpus (or any filesystem path) must be reasonably
# narrow: no path separators, no traversal segments, no whitespace, no NULs.
# Phase E tightens the client-code variant further (see ClientCode below) so
# only callers' own customer IDs can be supplied — adversarial source IDs are
# rejected at the request boundary.
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# Phase E — every request body is "extra=forbid" by default. Unknown fields
# get a 422 instead of being silently ignored, which catches stale clients
# and a class of smuggling attacks where an attacker tacks on fields the
# server didn't expect.
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_source_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("identifier must be a string")
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError("identifier may not contain path-traversal sequences")
    if not _SOURCE_ID_PATTERN.match(value):
        raise ValueError(
            "identifier must be 1–64 chars of letters, digits, dots, dashes, "
            "or underscores"
        )
    return value


SafeSourceId = Annotated[str | None, AfterValidator(_validate_source_id)]


# ---------------------------------------------------------------------------
# Auth (Phase B)
# ---------------------------------------------------------------------------


class LoginRequest(StrictModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=1)
    tenant_slug: str | None = None
    mfa_code: str | None = None
    mfa_token: str | None = None

    @model_validator(mode="after")
    def _validate_login_shape(self) -> "LoginRequest":
        if self.mfa_token:
            if not self.mfa_code:
                raise ValueError("mfa_code is required with mfa_token")
            return self
        if not self.email or not self.password:
            raise ValueError("email and password are required")
        return self


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class MFAChallengeResponse(BaseModel):
    status: str  # "mfa_required" | "mfa_enrollment_required"
    detail: str | None = None
    mfa_token: str | None = None


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(StrictModel):
    email: EmailStr
    tenant_slug: str | None = None


class ResetPasswordRequest(StrictModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=12)


class InviteRequest(StrictModel):
    email: EmailStr
    role: str = Field(default="advisor")


class AcceptInviteRequest(StrictModel):
    token: str = Field(min_length=10)
    password: str = Field(min_length=12)
    display_name: str | None = None


class AcceptInviteResponse(BaseModel):
    """Response after accepting an invitation.

    For non-MFA roles (advisor, compliance) only `status` and `user_id` are
    set — the user just signs in normally next.

    For MFA roles (admin, owner) the response also carries a staged TOTP
    secret + a short-lived `mfa_setup_token`. The invitee must immediately
    POST that token + a current authenticator code to `/auth/bootstrap/complete`
    to flip MFA on and receive a session. Without that second step they
    have a password but cannot log in (role gates them on enrolment)."""

    status: str = "created"
    user_id: str
    requires_mfa_setup: bool = False
    mfa_setup_token: str | None = None
    mfa_secret: str | None = None
    provisioning_uri: str | None = None


class MFAEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MFAVerifyRequest(StrictModel):
    code: str = Field(min_length=4)


class MFAVerifyResponse(BaseModel):
    recovery_codes: list[str]


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    email: str
    display_name: str | None = None
    role: str
    mfa_enrolled: bool
    can_use_byo_keys: bool = False


# ---------------------------------------------------------------------------
# First-admin bootstrap (resolves the chicken-and-egg: admin needs MFA to log
# in, but MFA enrollment needs a session). Two-step: begin returns a TOTP
# secret + short-lived token, complete verifies the code and mints a session.
# ---------------------------------------------------------------------------


class BootstrapBeginRequest(StrictModel):
    setup_key: str = Field(min_length=10, max_length=256)
    tenant_slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    tenant_name: str | None = Field(default=None, max_length=255)
    email: EmailStr
    password: str = Field(min_length=12)
    display_name: str | None = Field(default=None, max_length=255)


class BootstrapBeginResponse(BaseModel):
    bootstrap_token: str
    mfa_secret: str
    provisioning_uri: str
    user_id: str


class BootstrapCompleteRequest(StrictModel):
    bootstrap_token: str = Field(min_length=10)
    mfa_code: str = Field(min_length=4, max_length=12)


class BootstrapCompleteResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    recovery_codes: list[str]


class AskRequest(StrictModel):
    """Ask payload.

    Phase E: ``byo_key`` is no longer accepted here. Enrol a key once via
    ``POST /users/me/byo-keys`` and the server loads + decrypts it for each
    call — the plaintext never crosses the network after enrollment.
    """

    question: str = Field(min_length=3, max_length=4_000)
    client_id: SafeSourceId = None


class Citation(BaseModel):
    source_id: str
    source_type: str
    snippet: str


class Trust(BaseModel):
    grounding_score: float | None = None
    determinism_score: float | None = None
    model_route: str | None = None
    retrieval_ms: int | None = None
    generation_ms: int | None = None
    verification_ms: int | None = None
    total_ms: int | None = None
    evidence_quality: float | None = None
    cache_hit: bool = False


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
    file: str | None = None
    chunk_index: int | None = None
    source_version: str | None = None
    selected_reason: str | None = None


class ClaimOut(BaseModel):
    id: str | None = None
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
    llm_model: str | None = None


ReviewAssessment = Literal["correct", "needs_signoff", "incorrect", "insufficient_evidence"]
ReviewReasonCode = Literal[
    "concentration_breach",
    "liquidity_floor",
    "sector_exclusion",
    "region_exclusion",
    "tax_out_of_scope",
    "suitability_mismatch",
    "other",
]


class ClaimVerdict(StrictModel):
    claim_id: str = Field(min_length=1, max_length=64)
    supported: bool


class ReviewCreateRequest(StrictModel):
    assessment: ReviewAssessment
    reason_code: ReviewReasonCode
    notes: str | None = Field(default=None, max_length=4_000)
    # Only meaningful when the reviewer says the AI was wrong.
    corrected_outcome: Literal["answered", "flagged", "refused"] | None = None
    claim_verdicts: list[ClaimVerdict] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _correction_needs_incorrect_assessment(self) -> "ReviewCreateRequest":
        if self.corrected_outcome and self.assessment != "incorrect":
            raise ValueError("corrected_outcome is only allowed when assessment is 'incorrect'")
        return self


class ClaimLabelOut(BaseModel):
    claim_id: str
    claim_text: str
    cited_source_id: str | None = None
    supported: bool


class ReviewOut(BaseModel):
    id: str
    decision_id: str
    escalation_id: str | None = None
    escalation_status: str | None = None
    reviewer_user_id: str
    reviewer_email: str | None = None
    assessment: str
    reason_code: str
    notes: str | None = None
    corrected_outcome: str | None = None
    created_at: str
    claim_labels: list[ClaimLabelOut] = []


class CorrectionOut(BaseModel):
    id: str
    corrected_by_user_id: str
    corrected_outcome: str | None = None
    note: str
    created_at: str


class EscalationBrief(BaseModel):
    id: str
    status: str
    priority: str
    sla_due_at: str
    assigned_to_user_id: str | None = None


class AuditDetail(AuditSummary):
    asked_by: str | None = None
    prev_hash: str | None = None
    row_hash: str | None = None
    final_answer: str | None
    retrieved_chunks: list[RetrievedChunkOut]
    decision_claims: list[ClaimOut]
    reviews: list[ReviewOut] = []
    corrections: list[CorrectionOut] = []
    active_escalation: EscalationBrief | None = None


class AuditVerifyResponse(BaseModel):
    tenant_id: str
    ok: bool
    total: int
    verified: int
    first_break_decision_id: str | None
    first_break_reason: str | None
    tail_hash: str | None


class EscalationCreateRequest(StrictModel):
    decision_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="advisor_requested_review", min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2_000)


class EscalationUpdateRequest(StrictModel):
    status: str | None = Field(default=None, pattern=r"^(open|in_review|resolved|cancelled)$")
    assigned_to_user_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2_000)


class EscalationEventOut(BaseModel):
    id: str
    action: str
    actor_user_id: str
    from_status: str | None = None
    to_status: str | None = None
    note: str | None = None
    created_at: str


class EscalationOut(BaseModel):
    id: str
    decision_id: str
    client_id: str | None = None
    question: str | None = None
    decision_outcome: str | None = None
    decision_created_at: str | None = None
    grounding_score: float | None = None
    latency_ms: int | None = None
    status: str
    priority: str
    reason: str
    note: str | None = None
    assigned_role: str
    assigned_to_user_id: str | None = None
    created_by_user_id: str
    sla_due_at: str
    created_at: str
    updated_at: str
    events: list[EscalationEventOut] = []


class MetricsSummary(BaseModel):
    total: int
    hallucination_rate: float
    refusal_rate: float
    flagged_rate: float
    avg_determinism: float | None
    audit_completeness: float
    reviews: int = 0
    labelled_claims: int = 0
    # answered / flagged / refused / fallback -> number of decisions
    outcome_counts: dict[str, int] = {}


class MetricsPoint(BaseModel):
    """One UTC day. Rates are None on days without decisions, so charts
    show a gap instead of a misleading zero."""

    date: str
    total: int
    answered: int = 0
    flagged: int = 0
    refused: int = 0
    fallback: int = 0
    hallucination_rate: float | None = None
    refusal_rate: float | None = None
    flagged_rate: float | None = None
    audit_completeness: float | None = None
    avg_determinism: float | None = None


class MetricsTimeseries(BaseModel):
    days: int
    start: str
    end: str
    points: list[MetricsPoint]


# ---------------------------------------------------------------------------
# Clients (Phase D — replaces frontend localStorage)
# ---------------------------------------------------------------------------


# Phase E tightens the client_code regex to ``^C[0-9]{3,6}$`` per
# docs/SECURITY-IMPLEMENTATION.md. Anything outside this shape (test fixtures,
# legacy migrated codes) goes through ``LegacyClientCode`` which keeps the
# Phase D allowlist. New code paths should use ``ClientCode`` exclusively.
_CLIENT_CODE_PATTERN = re.compile(r"^C[0-9]{3,6}$")
_LEGACY_CLIENT_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,15}$")


def _validate_client_code(value: str) -> str:
    upper = value.strip().upper()
    if not _CLIENT_CODE_PATTERN.match(upper):
        raise ValueError(
            "client_code must match ^C[0-9]{3,6}$ (e.g. C001, C12345)"
        )
    return upper


def _validate_legacy_client_code(value: str) -> str:
    upper = value.strip().upper()
    if not _LEGACY_CLIENT_CODE_PATTERN.match(upper):
        raise ValueError(
            "client_code must start with a letter and be 2–16 chars of "
            "letters, digits, dashes, or underscores"
        )
    return upper


ClientCode = Annotated[str, AfterValidator(_validate_client_code)]
LegacyClientCode = Annotated[str, AfterValidator(_validate_legacy_client_code)]


class ClientOut(BaseModel):
    id: str
    client_code: str
    display_name: str
    household: str | None = None
    risk_profile: str
    jurisdictions: list[str] = []
    max_single_position_pct: float | None = None
    min_liquid_within_30d_pct: float | None = None
    excluded_sectors: list[str] = []
    excluded_regions: list[str] = []
    ips_version: str | None = None
    ips_updated_at: str | None = None
    aum_eur: float | None = None
    advisor_name: str | None = None
    created_at: str


class ClientCreateRequest(StrictModel):
    client_code: ClientCode
    display_name: str = Field(min_length=1, max_length=255)
    household: str | None = Field(default=None, max_length=255)
    risk_profile: str = Field(pattern=r"^(conservative|moderate|aggressive)$")
    jurisdictions: list[str] = Field(default_factory=list, max_length=10)
    max_single_position_pct: float | None = Field(default=None, ge=0, le=100)
    min_liquid_within_30d_pct: float | None = Field(default=None, ge=0, le=100)
    excluded_sectors: list[str] = Field(default_factory=list, max_length=20)
    excluded_regions: list[str] = Field(default_factory=list, max_length=20)
    ips_version: str | None = Field(default=None, max_length=32)
    ips_updated_at: str | None = Field(default=None, max_length=32)
    aum_eur: float | None = Field(default=None, ge=0)
    advisor_name: str | None = Field(default=None, max_length=255)


class DeterminismRequest(StrictModel):
    question: str = Field(min_length=3, max_length=4_000)
    client_id: SafeSourceId = None
    runs: int | None = Field(default=None, ge=2, le=10)
    alternate_model: str | None = None


class DeterminismResponse(BaseModel):
    determinism_score: float
    representative_decision_id: str | None
    per_run_outcomes: list[AskResponse]


class ModelHealth(BaseModel):
    provider: str
    label: str
    model: str
    route: str
    configured: bool
    healthy: bool
    available: bool
    production_eligible: bool
    blocked_reason: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    chat_usable: bool = False
    smoke_latency_ms: int | None = None
    smoke_error: str | None = None


class AskRuntimeStatus(BaseModel):
    mode: str
    production_mode: bool
    active_route: str | None = None
    fallback_enabled: bool
    status: str
    message: str | None = None


class ProductionModelRouteStatus(BaseModel):
    provider: str
    label: str
    model: str
    route: str
    configured: bool
    production_eligible: bool
    blocked_reason: str | None = None
    approved_for_inference: bool
    ready_for_inference: bool = False
    chat_usable: bool = False
    smoke_latency_ms: int | None = None
    smoke_error: str | None = None
    approval: dict
    prompt_profile: dict


class ProductionModelStatus(BaseModel):
    production_mode: bool
    product_inference_allowed: bool
    active_route: str | None = None
    candidate_routes: list[str]
    approved_routes: list[str]
    ready_routes: list[str] = []
    active_route_health: dict | None = None
    required_eval_questions: int
    eval_freshness_hours: int
    require_recent_eval: bool
    approved_models_env: str
    blocked_reason: str | None = None
    local_evidence_mode: bool = False
    model_gate_required: bool = True
    routes: list[ProductionModelRouteStatus]


class ModelLeaderboardRow(BaseModel):
    run_id: str | None = None
    created_at: str | None = None
    provider: str
    label: str
    model: str
    route: str
    status: str
    production_ready: bool
    overall_score: float
    outcome_accuracy: float
    citation_accuracy: float
    retrieval_recall: float = 0.0
    faithfulness_score: float = 0.0
    golden_claim_score: float = 0.0
    hallucination_rate: float
    avg_latency_ms: int | None = None
    p50_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    determinism: float
    answerability_accuracy: float = 0.0
    refusal_correctness: float = 0.0
    numeric_compliance_accuracy: float = 0.0
    prompt_injection_resistance: float = 0.0
    advisor_quality_score: float = 0.0
    evaluated_questions: int
    dataset_size: int | None = None
    dataset_version: str | None = None
    category_scores: dict = {}
    failure_buckets: dict = {}
    eval_gate: str = "fast"
    failure_examples: list[dict] = []
    error: str | None = None
    health: dict | None = None


class ModelLeaderboard(BaseModel):
    dataset_version: str
    dataset_size: int
    evaluated_questions: int
    thresholds: dict
    models: list[ModelLeaderboardRow]


class GuardrailStatus(BaseModel):
    key: str
    label: str
    enabled: bool
    detail: str | None = None
    # Environment variable that controls it; None means always on.
    setting: str | None = None


class RateLimitInfo(BaseModel):
    auth_per_min: int
    ask_per_min: int
    default_per_min: int


class SystemInfo(BaseModel):
    version: str
    environment: str
    database: str
    inference_mode: str
    inference_route: str | None = None
    embedding_backend: str
    rate_limits: RateLimitInfo
    max_ask_body_bytes: int
    audit_retention: str
    guardrails: list[GuardrailStatus]


class AccessRequestCreate(StrictModel):
    """Public contact form. `website` is a honeypot: people never see the
    field, so a non-empty value marks an automated submission."""

    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=160)
    work_email: EmailStr
    role: str = Field(min_length=1, max_length=120)
    message: str | None = Field(default=None, max_length=4_000)
    website: str | None = Field(default=None, max_length=200)


class AccessRequestReceived(BaseModel):
    status: str = "received"
