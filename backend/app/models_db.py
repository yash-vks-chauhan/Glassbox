from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """``DateTime(timezone=True)`` that always reads back as aware UTC.

    Postgres keeps the zone; SQLite drops it and returns naive datetimes,
    which the API then serialised without an offset, so browsers read UTC
    times as local ones (an advisor in Zurich saw every time two hours
    early, and SLA countdowns were off by the same amount). Aware values
    are stored as UTC; naive ones are taken to be UTC already."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def new_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Fixed UUID for the seed tenant used to backfill pre-tenancy rows.
DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Identity & access
# ---------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    plan: Mapped[str] = mapped_column(String(24), nullable=False, default="standard")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    clients: Mapped[list["ClientRecord"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index("ix_users_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="advisor")
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Encrypted TOTP secret + recovery-code hashes; see app.core.auth.mfa.
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class UserInvitation(Base):
    __tablename__ = "user_invitations"
    __table_args__ = (
        Index("ix_user_invitations_tenant_id", "tenant_id"),
        Index("ix_user_invitations_email", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="advisor")
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_family_id", "family_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    # All rotated descendants of one login share a family_id. Reuse of any
    # superseded token in the family means token theft -> revoke whole family.
    family_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class PasswordReset(Base):
    __tablename__ = "password_resets"
    __table_args__ = (Index("ix_password_resets_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class ByoKey(Base):
    __tablename__ = "byo_keys"
    __table_args__ = (
        Index("ix_byo_keys_user_id", "user_id"),
        UniqueConstraint("user_id", "provider", name="uq_byo_keys_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # AES-GCM ciphertext stored as base64(nonce || ciphertext || tag).
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_kid: Mapped[str] = mapped_column(String(32), nullable=False)
    # Last 4 chars of the original plaintext key for UX (so users can pick
    # the right one). Never store more — that's leakable.
    last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_tenant_id", "tenant_id"),
        Index("ix_security_events_user_id", "user_id"),
        Index("ix_security_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


# ---------------------------------------------------------------------------
# Tenant-owned business data
# ---------------------------------------------------------------------------


class ClientRecord(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_code", name="uq_clients_tenant_code"),
        Index("ix_clients_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    client_code: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    household: Mapped[str | None] = mapped_column(String(255), nullable=True)
    risk_profile: Mapped[str] = mapped_column(String(24), nullable=False)
    jurisdictions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    max_single_position_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_liquid_within_30d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    excluded_sectors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    excluded_regions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ips_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ips_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    aum_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    advisor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    tenant: Mapped[Tenant] = relationship(back_populates="clients")


# ---------------------------------------------------------------------------
# Audit / decisions  (now tenant-scoped)
# ---------------------------------------------------------------------------


class Thread(Base):
    """A conversation about one client. Each question asked in it is a
    decision carrying ``thread_id``."""

    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_tenant_id", "tenant_id"),
        Index("ix_threads_client_id", "client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # open | resolved | escalated
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_tenant_id", "tenant_id"),
        Index("ix_decisions_user_id", "user_id"),
        Index("ix_decisions_created_at", "created_at"),
        Index("ix_decisions_thread_id", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    determinism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    grounding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Phase E — tamper-evident hash chain.
    # `prev_hash` points at the previous decision in the (tenant_id) chain;
    # `row_hash` = sha256(prev_hash || canonical_json(this_row)). NULL on
    # legacy rows until the chain is backfilled.
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Conversation context, hashed when set (see OPTIONAL_HASHED_DECISION_FIELDS):
    # the thread this question belongs to, the context-resolved question that
    # retrieval actually used for a follow-up, and the refusal text shown.
    thread_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("threads.id"), nullable=True
    )
    retrieval_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    claims: Mapped[list["DecisionClaim"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    retrieved_chunks: Mapped[list["RetrievedChunk"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    escalations: Mapped[list["Escalation"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class DecisionClaim(Base):
    __tablename__ = "decision_claims"
    __table_args__ = (Index("ix_decision_claims_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    cited_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    decision: Mapped[Decision] = relationship(back_populates="claims")


class RetrievedChunk(Base):
    __tablename__ = "retrieved_chunks"
    __table_args__ = (Index("ix_retrieved_chunks_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    decision: Mapped[Decision] = relationship(back_populates="retrieved_chunks")


class DecisionCorrection(Base):
    """Phase E — append-only correction log.

    Because `decisions`, `decision_claims`, and `retrieved_chunks` form a
    tamper-evident hash chain, we never mutate them. If a later review needs
    to revise an outcome, a row lands here, citing the original decision_id
    and an explanation.
    """

    __tablename__ = "decision_corrections"
    __table_args__ = (
        Index("ix_decision_corrections_tenant_id", "tenant_id"),
        Index("ix_decision_corrections_decision_id", "decision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    corrected_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    corrected_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        Index("ix_escalations_tenant_id", "tenant_id"),
        Index("ix_escalations_decision_id", "decision_id"),
        Index("ix_escalations_status", "status"),
        # One *active* escalation per decision. The partial predicate has to
        # be spelled per dialect, otherwise Postgres builds a plain unique
        # index and a resolved escalation blocks every later one.
        Index(
            "uq_escalations_active_decision",
            "tenant_id",
            "decision_id",
            unique=True,
            sqlite_where=text("status IN ('open', 'in_review')"),
            postgresql_where=text("status IN ('open', 'in_review')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    assigned_role: Mapped[str] = mapped_column(
        String(24), nullable=False, default="compliance"
    )
    assigned_to_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    decision: Mapped[Decision] = relationship(back_populates="escalations")
    events: Mapped[list["EscalationEvent"]] = relationship(
        back_populates="escalation", cascade="all, delete-orphan"
    )


class EscalationEvent(Base):
    __tablename__ = "escalation_events"
    __table_args__ = (
        Index("ix_escalation_events_tenant_id", "tenant_id"),
        Index("ix_escalation_events_escalation_id", "escalation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    escalation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("escalations.id"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    escalation: Mapped[Escalation] = relationship(back_populates="events")


class DecisionReview(Base):
    """A compliance reviewer's verdict on one decision. Append-only: a later
    review supersedes an earlier one without editing it."""

    __tablename__ = "decision_reviews"
    __table_args__ = (
        Index("ix_decision_reviews_tenant_id", "tenant_id"),
        Index("ix_decision_reviews_decision_id", "decision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    escalation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("escalations.id"), nullable=True
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    # correct | needs_signoff | incorrect | insufficient_evidence
    assessment: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    claim_labels: Mapped[list["ClaimLabel"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class ClaimLabel(Base):
    """Reviewer verdict on one claim: did its cited source support it?
    Claim and source text are copied so the row stands alone as a labelled
    training example for the grounding scorer."""

    __tablename__ = "claim_labels"
    __table_args__ = (
        Index("ix_claim_labels_tenant_id", "tenant_id"),
        Index("ix_claim_labels_review_id", "review_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decision_reviews.id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False
    )
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decision_claims.id"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    cited_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    review: Mapped[DecisionReview] = relationship(back_populates="claim_labels")


class DeterminismSchedule(Base):
    """When the determinism harness runs for a tenant (at most once a day)."""

    __tablename__ = "determinism_schedules"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    runs_per_question: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


class DeterminismRun(Base):
    """One run of the harness: each sampled question asked several times
    without recording decisions, scored for how much the answers drift."""

    __tablename__ = "determinism_runs"
    __table_args__ = (
        Index("ix_determinism_runs_tenant_id", "tenant_id"),
        Index("ix_determinism_runs_created_at", "created_at"),
        # A scheduled run is claimed by inserting its (tenant, date) row, so
        # two server processes can't both run the same day's job.
        UniqueConstraint("tenant_id", "scheduled_for", name="uq_determinism_runs_schedule_day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    # schedule | manual
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    scheduled_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    # running | completed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    model_route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runs_per_question: Mapped[int] = mapped_column(Integer, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RateLimitBucket(Base):
    """Phase E — persistent per-(subject, route_class) sliding window.

    Each row represents one bucket; `hits_json` is a JSON-encoded sorted list
    of unix epoch seconds in the last 60 seconds. We trim on every write.
    SQLite is fine for the demo footprint; switching to Redis later means
    swapping the implementation in app.core.security.rate_limit, not the model.
    """

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        Index("ix_rate_limit_buckets_subject", "subject"),
        UniqueConstraint("subject", "route_class", name="uq_rate_limit_subject_route"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    route_class: Mapped[str] = mapped_column(String(32), nullable=False)
    hits_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )


# ---------------------------------------------------------------------------
# Model evaluation  (platform-wide; tenant_id nullable)
# ---------------------------------------------------------------------------


class ModelEvalRun(Base):
    __tablename__ = "model_eval_runs"
    __table_args__ = (Index("ix_model_eval_runs_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    route: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_size: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    thresholds_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    category_scores_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    production_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    faithfulness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    golden_claim_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hallucination_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    avg_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p50_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p95_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    determinism: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    answerability_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    refusal_correctness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    numeric_compliance_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_injection_resistance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    advisor_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    failure_buckets_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    eval_gate: Mapped[str] = mapped_column(String(16), nullable=False, default="fast")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list["ModelEvalResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ModelEvalResult(Base):
    __tablename__ = "model_eval_results"
    __table_args__ = (Index("ix_model_eval_results_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_eval_runs.id"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    actual_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    faithfulness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    golden_claim_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    answerability_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    refusal_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    numeric_compliance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_injection_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    advisor_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hallucinated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    cited_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retrieved_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    banned_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_bucket: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    gold_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    adversarial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[ModelEvalRun] = relationship(back_populates="results")


# ---------------------------------------------------------------------------
# Marketing site
# ---------------------------------------------------------------------------


class AccessRequest(Base):
    """A "request a walkthrough" submission from the public contact page.
    Platform-level (there is no tenant yet), never shown to tenant users."""

    __tablename__ = "access_requests"
    __table_args__ = (Index("ix_access_requests_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str] = mapped_column(String(160), nullable=False)
    work_email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
