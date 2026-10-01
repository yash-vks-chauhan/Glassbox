import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.audit_export import (
    CSV_MAX_ROWS,
    PDF_MAX_DECISIONS,
    AuditFilters,
    export_csv,
    export_pdf,
    filtered_decisions,
    load_for_export,
)
from app.core.auth.deps import current_user, require_role
from app.core.escalations import escalation_brief
from app.core.reviews import (
    active_escalation,
    corrections_for_decision,
    reviews_for_decision,
)
from app.core.security.audit_hash import verify_chain
from app.db import get_db
from app.models_db import Decision, SecurityEvent, User
from app.schemas import (
    AuditDetail,
    AuditSummary,
    AuditVerifyResponse,
    ClaimOut,
    RetrievedChunkOut,
)


router = APIRouter(tags=["audit"])


# Roles permitted to see *every* decision in their tenant. Advisors see only
# their own audits — they don't get to read another advisor's traces.
_TENANT_WIDE_AUDIT_ROLES = frozenset({"compliance", "admin", "owner"})
_VERIFY_ROLES = ("compliance", "admin", "owner")


def _scoped_decision_query(user: User):
    """Base SELECT that already filters by tenant + (for advisors) by user."""
    stmt = select(Decision).where(Decision.tenant_id == user.tenant_id)
    if user.role not in _TENANT_WIDE_AUDIT_ROLES:
        stmt = stmt.where(Decision.user_id == user.id)
    return stmt


Outcome = Literal["answered", "flagged", "refused", "fallback"]


def audit_filters(
    outcome: Outcome | None = Query(default=None),
    client_id: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None, description="inclusive, ISO 8601"),
    until: datetime | None = Query(default=None, description="exclusive, ISO 8601"),
    grounding: Literal["low"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> AuditFilters:
    return AuditFilters(
        outcome=outcome,
        client_id=client_id or None,
        since=_utc(since),
        until=_utc(until),
        low_grounding=grounding == "low",
        q=(q or "").strip() or None,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/audit", response_model=list[AuditSummary])
def list_audit(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    filters: AuditFilters = Depends(audit_filters),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[AuditSummary]:
    """Newest first. The total number of matching decisions is returned in
    the ``X-Total-Count`` header for paging."""
    stmt = filtered_decisions(user, filters)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(total)
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return [_summary(row) for row in rows]


# IMPORTANT: register /audit/export and /audit/verify BEFORE /audit/{decision_id}.
@router.get("/audit/export")
def export_audit(
    request: Request,
    format: Literal["csv", "pdf"] = Query(default="csv"),
    filters: AuditFilters = Depends(audit_filters),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_VERIFY_ROLES)),
) -> Response:
    """Download the filtered audit log as CSV or as a PDF audit binder.
    Every export is itself recorded as a security event."""
    stmt = filtered_decisions(user, filters)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    cap = PDF_MAX_DECISIONS if format == "pdf" else CSV_MAX_ROWS
    if total > cap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{total} decisions match; a {format.upper()} export holds at most {cap}. "
                "Narrow the date range or filters."
            ),
        )
    decisions = load_for_export(db, stmt)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    if format == "pdf":
        body = export_pdf(db, user=user, decisions=decisions, filters=filters)
        media_type, filename = "application/pdf", f"glassbox-audit-binder-{stamp}.pdf"
    else:
        body = export_csv(db, decisions).encode("utf-8")
        media_type, filename = "text/csv; charset=utf-8", f"glassbox-audit-{stamp}.csv"

    db.add(
        SecurityEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            kind="audit_export",
            ip=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
            metadata_json=json.dumps(
                {"format": format, "decisions": total, "filters": filters.describe()}
            ),
        )
    )
    db.commit()
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# FastAPI matches routes top-down, so the generic path-parameter route below
# would otherwise swallow these and try to load a Decision with id "verify".
@router.get("/audit/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_VERIFY_ROLES)),
) -> AuditVerifyResponse:
    """Walk the caller's tenant hash chain and report the first break, if
    any. Compliance+ only — random advisors don't run integrity audits.

    A 200 with ``ok: true`` means every decision row's stored hash matches
    the canonical hash of its content + the prior row's hash, all the way
    back to genesis. A 200 with ``ok: false`` points at the first row that
    diverges plus an interpretable reason."""
    report = verify_chain(db, tenant_id=user.tenant_id)
    return AuditVerifyResponse(
        tenant_id=report.tenant_id,
        ok=report.ok,
        total=report.total,
        verified=report.verified,
        first_break_decision_id=report.first_break_decision_id,
        first_break_reason=report.first_break_reason,
        tail_hash=report.tail_hash,
    )


@router.get("/audit/{decision_id}", response_model=AuditDetail)
def get_audit(
    decision_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditDetail:
    row = db.scalar(
        _scoped_decision_query(user)
        .where(Decision.id == decision_id)
        .options(selectinload(Decision.claims), selectinload(Decision.retrieved_chunks))
    )
    if row is None:
        # 404 deliberately — never 403 — so cross-tenant probes can't confirm
        # whether a decision_id exists in another tenant.
        raise HTTPException(status_code=404, detail="Decision not found")
    asker = db.get(User, row.user_id) if row.user_id else None
    return AuditDetail(
        **_summary(row).model_dump(),
        asked_by=asker.email if asker else None,
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
        thread_id=row.thread_id,
        retrieval_question=row.retrieval_question,
        refusal_reason=row.refusal_reason,
        final_answer=row.final_answer,
        retrieved_chunks=[
            RetrievedChunkOut(
                source_id=chunk.source_id,
                source_type=chunk.source_type,
                chunk_text=chunk.chunk_text,
                score=chunk.score,
                file=chunk.file,
                chunk_index=chunk.chunk_index,
                source_version=chunk.source_version,
                selected_reason=chunk.selected_reason,
            )
            for chunk in row.retrieved_chunks
        ],
        decision_claims=[
            ClaimOut(
                id=claim.id,
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                verified=claim.verified,
                kept=claim.kept,
            )
            for claim in row.claims
        ],
        reviews=reviews_for_decision(db, tenant_id=row.tenant_id, decision_id=row.id),
        corrections=corrections_for_decision(db, tenant_id=row.tenant_id, decision_id=row.id),
        active_escalation=escalation_brief(
            active_escalation(db, tenant_id=row.tenant_id, decision_id=row.id)
        ),
    )


def _summary(row: Decision) -> AuditSummary:
    return AuditSummary(
        id=row.id,
        created_at=row.created_at.isoformat(),
        question=row.question,
        client_id=row.client_id,
        outcome=row.outcome,
        grounding_score=row.grounding_score,
        determinism_score=row.determinism_score,
        latency_ms=row.latency_ms,
        llm_model=row.llm_model,
    )
