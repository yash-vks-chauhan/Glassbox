"""Compliance review of decisions.

A review records the reviewer's assessment, labels individual claims as
supported or not (training data for the grounding scorer), moves the
decision's escalation along, and, when the AI was wrong, appends a
correction. Decisions themselves are hash-chained and never edited.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.escalations import ACTIVE_STATUSES, ESCALATION_SLA, append_event
from app.models_db import (
    ClaimLabel,
    Decision,
    DecisionCorrection,
    DecisionReview,
    Escalation,
    User,
    utcnow,
)
from app.schemas import (
    ClaimLabelOut,
    CorrectionOut,
    EscalationBrief,
    ReviewCreateRequest,
    ReviewOut,
)


# Assessments that settle the question; the others need more eyes.
_SETTLING_ASSESSMENTS = frozenset({"correct", "incorrect"})


def active_escalation(db: Session, *, tenant_id: str, decision_id: str) -> Escalation | None:
    return db.scalar(
        select(Escalation)
        .where(
            Escalation.tenant_id == tenant_id,
            Escalation.decision_id == decision_id,
            Escalation.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Escalation.created_at.desc())
    )


def submit_review(
    db: Session, *, decision: Decision, reviewer: User, payload: ReviewCreateRequest
) -> DecisionReview:
    """Record a review. ``decision`` must be loaded with claims and chunks and
    already be scoped to the reviewer's tenant. Commits the transaction."""
    if decision.user_id == reviewer.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Four-eyes rule: a decision can't be reviewed by the person who asked it.",
        )
    claims_by_id = {claim.id: claim for claim in decision.claims}
    unknown = sorted({v.claim_id for v in payload.claim_verdicts} - claims_by_id.keys())
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Claims not part of this decision: {', '.join(unknown)}",
        )

    escalation = active_escalation(db, tenant_id=decision.tenant_id, decision_id=decision.id)
    review = DecisionReview(
        tenant_id=decision.tenant_id,
        decision_id=decision.id,
        escalation_id=escalation.id if escalation else None,
        reviewer_user_id=reviewer.id,
        assessment=payload.assessment,
        reason_code=payload.reason_code,
        notes=(payload.notes or "").strip() or None,
        corrected_outcome=payload.corrected_outcome,
    )
    db.add(review)
    db.flush()

    source_text = _source_text_by_id(decision)
    # One label per claim; a repeated claim id keeps the last verdict sent.
    verdicts = {v.claim_id: v.supported for v in payload.claim_verdicts}
    for claim_id, supported in verdicts.items():
        claim = claims_by_id[claim_id]
        db.add(
            ClaimLabel(
                tenant_id=decision.tenant_id,
                review_id=review.id,
                decision_id=decision.id,
                claim_id=claim.id,
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                source_text=source_text.get(claim.cited_source_id or ""),
                supported=supported,
            )
        )

    if payload.assessment == "incorrect":
        db.add(
            DecisionCorrection(
                tenant_id=decision.tenant_id,
                decision_id=decision.id,
                corrected_by_user_id=reviewer.id,
                corrected_outcome=payload.corrected_outcome,
                note=review.notes or f"Reviewer marked the decision incorrect ({review.reason_code}).",
            )
        )

    escalation = _advance_escalation(db, decision, escalation, review, reviewer)
    review.escalation_id = escalation.id if escalation else None
    db.commit()
    db.refresh(review)
    return review


def _source_text_by_id(decision: Decision) -> dict[str, str]:
    """Text the decision actually retrieved for each source id."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for chunk in decision.retrieved_chunks:
        grouped[chunk.source_id].append(chunk.chunk_text)
    return {source_id: "\n".join(texts) for source_id, texts in grouped.items()}


def _advance_escalation(
    db: Session,
    decision: Decision,
    escalation: Escalation | None,
    review: DecisionReview,
    reviewer: User,
) -> Escalation | None:
    note = f"Review: {review.assessment} · {review.reason_code}"
    if review.assessment in _SETTLING_ASSESSMENTS:
        if escalation is None:
            return None
        previous = escalation.status
        escalation.status = "resolved"
        escalation.updated_at = utcnow()
        append_event(
            db, escalation, actor=reviewer, action="reviewed",
            from_status=previous, to_status="resolved", note=note,
        )
        return escalation

    # Needs a supervisor's sign-off or more evidence: keep (or put) it in
    # the queue at high priority, unassigned so someone else picks it up.
    now = utcnow()
    if escalation is None:
        escalation = Escalation(
            tenant_id=decision.tenant_id,
            decision_id=decision.id,
            client_id=decision.client_id,
            created_by_user_id=reviewer.id,
            assigned_role="compliance",
            status="open",
            priority="high",
            reason=f"review_{review.assessment}",
            note=review.notes,
            sla_due_at=now + ESCALATION_SLA,
            created_at=now,
            updated_at=now,
        )
        db.add(escalation)
        db.flush()
        append_event(
            db, escalation, actor=reviewer, action="created", to_status="open", note=note
        )
        return escalation
    previous = escalation.status
    escalation.status = "in_review" if review.assessment == "needs_signoff" else "open"
    escalation.priority = "high"
    escalation.assigned_to_user_id = None
    escalation.updated_at = now
    append_event(
        db, escalation, actor=reviewer, action="reviewed",
        from_status=previous, to_status=escalation.status, note=note,
    )
    return escalation


# ---------------------------------------------------------------------------
# Serialisation (shared with the audit router)
# ---------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.isoformat()


def reviews_for_decision(db: Session, *, tenant_id: str, decision_id: str) -> list[ReviewOut]:
    rows = db.scalars(
        select(DecisionReview)
        .where(DecisionReview.tenant_id == tenant_id, DecisionReview.decision_id == decision_id)
        .options(selectinload(DecisionReview.claim_labels))
        .order_by(DecisionReview.created_at.desc())
    ).all()
    return [review_out(db, row) for row in rows]


def review_out(db: Session, row: DecisionReview) -> ReviewOut:
    reviewer = db.get(User, row.reviewer_user_id)
    escalation = db.get(Escalation, row.escalation_id) if row.escalation_id else None
    return ReviewOut(
        id=row.id,
        decision_id=row.decision_id,
        escalation_id=row.escalation_id,
        escalation_status=escalation.status if escalation else None,
        reviewer_user_id=row.reviewer_user_id,
        reviewer_email=reviewer.email if reviewer else None,
        assessment=row.assessment,
        reason_code=row.reason_code,
        notes=row.notes,
        corrected_outcome=row.corrected_outcome,
        created_at=_iso(row.created_at),
        claim_labels=[
            ClaimLabelOut(
                claim_id=label.claim_id,
                claim_text=label.claim_text,
                cited_source_id=label.cited_source_id,
                supported=label.supported,
            )
            for label in row.claim_labels
        ],
    )


def corrections_for_decision(
    db: Session, *, tenant_id: str, decision_id: str
) -> list[CorrectionOut]:
    rows = db.scalars(
        select(DecisionCorrection)
        .where(
            DecisionCorrection.tenant_id == tenant_id,
            DecisionCorrection.decision_id == decision_id,
        )
        .order_by(DecisionCorrection.created_at.desc())
    ).all()
    return [
        CorrectionOut(
            id=row.id,
            corrected_by_user_id=row.corrected_by_user_id,
            corrected_outcome=row.corrected_outcome,
            note=row.note,
            created_at=_iso(row.created_at),
        )
        for row in rows
    ]


def escalation_brief(escalation: Escalation | None) -> EscalationBrief | None:
    if escalation is None:
        return None
    return EscalationBrief(
        id=escalation.id,
        status=escalation.status,
        priority=escalation.priority,
        sla_due_at=_iso(escalation.sla_due_at),
        assigned_to_user_id=escalation.assigned_to_user_id,
    )
