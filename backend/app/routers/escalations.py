from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth.deps import current_user, require_role
from app.db import get_db
from app.models_db import Decision, Escalation, EscalationEvent, User, utcnow
from app.schemas import (
    EscalationCreateRequest,
    EscalationEventOut,
    EscalationOut,
    EscalationUpdateRequest,
)


router = APIRouter(prefix="/escalations", tags=["escalations"])

_TENANT_WIDE_ROLES = frozenset({"compliance", "admin", "owner"})
_REVIEWER_ROLES = ("compliance", "admin", "owner")
_ACTIVE_STATUSES = ("open", "in_review")


def _scoped_decision_query(user: User):
    stmt = select(Decision).where(Decision.tenant_id == user.tenant_id)
    if user.role not in _TENANT_WIDE_ROLES:
        stmt = stmt.where(Decision.user_id == user.id)
    return stmt


def _scoped_escalation_query(user: User):
    stmt = select(Escalation).where(Escalation.tenant_id == user.tenant_id)
    if user.role not in _TENANT_WIDE_ROLES:
        stmt = stmt.where(Escalation.created_by_user_id == user.id)
    return stmt


@router.post("", response_model=EscalationOut, status_code=status.HTTP_201_CREATED)
def create_escalation(
    request: EscalationCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> EscalationOut:
    decision = db.scalar(
        _scoped_decision_query(user).where(Decision.id == request.decision_id)
    )
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    existing = db.scalar(
        select(Escalation)
        .where(
            Escalation.tenant_id == user.tenant_id,
            Escalation.decision_id == decision.id,
            Escalation.status.in_(_ACTIVE_STATUSES),
        )
        .options(selectinload(Escalation.events), selectinload(Escalation.decision))
        .order_by(Escalation.created_at.desc())
    )
    if existing is not None:
        _append_event(
            db,
            existing,
            actor=user,
            action="duplicate_requested",
            note=request.note,
        )
        db.commit()
        db.refresh(existing)
        return _out(existing)

    now = utcnow()
    escalation = Escalation(
        tenant_id=user.tenant_id,
        decision_id=decision.id,
        client_id=decision.client_id,
        created_by_user_id=user.id,
        assigned_role="compliance",
        status="open",
        priority="high" if decision.outcome in {"flagged", "refused"} else "normal",
        reason=request.reason,
        note=request.note,
        sla_due_at=now + timedelta(hours=4),
        created_at=now,
        updated_at=now,
    )
    db.add(escalation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Escalation)
            .where(
                Escalation.tenant_id == user.tenant_id,
                Escalation.decision_id == decision.id,
                Escalation.status.in_(_ACTIVE_STATUSES),
            )
            .options(selectinload(Escalation.events), selectinload(Escalation.decision))
            .order_by(Escalation.created_at.desc())
        )
        if existing is None:
            raise
        _append_event(
            db,
            existing,
            actor=user,
            action="duplicate_requested",
            note=request.note,
        )
        db.commit()
        db.refresh(existing)
        return _out(existing)
    _append_event(
        db,
        escalation,
        actor=user,
        action="created",
        to_status="open",
        note=request.note,
    )
    db.commit()
    db.refresh(escalation)
    return _out(escalation)


@router.get("", response_model=list[EscalationOut])
def list_escalations(
    limit: int = Query(default=100, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[EscalationOut]:
    stmt = _scoped_escalation_query(user).options(
        selectinload(Escalation.events), selectinload(Escalation.decision)
    )
    if status_filter:
        stmt = stmt.where(Escalation.status == status_filter)
    rows = db.scalars(
        stmt.order_by(Escalation.created_at.desc()).limit(limit)
    ).all()
    return [_out(row) for row in rows]


@router.patch("/{escalation_id}", response_model=EscalationOut)
def update_escalation(
    escalation_id: str,
    request: EscalationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_REVIEWER_ROLES)),
) -> EscalationOut:
    row = db.scalar(
        select(Escalation)
        .where(Escalation.tenant_id == user.tenant_id, Escalation.id == escalation_id)
        .options(selectinload(Escalation.events), selectinload(Escalation.decision))
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    previous_status = row.status
    changed = False
    if request.status and request.status != row.status:
        row.status = request.status
        changed = True
    if request.assigned_to_user_id is not None:
        assignee = _resolve_assignee(db, user, request.assigned_to_user_id)
        if assignee.id != row.assigned_to_user_id:
            row.assigned_to_user_id = assignee.id
            changed = True
    if request.note:
        row.note = request.note
        changed = True

    if changed:
        row.updated_at = utcnow()
        _append_event(
            db,
            row,
            actor=user,
            action="updated",
            from_status=previous_status,
            to_status=row.status,
            note=request.note,
        )
        db.commit()
        db.refresh(row)
    return _out(row)


def _resolve_assignee(db: Session, actor: User, assigned_to_user_id: str) -> User:
    target = db.get(User, assigned_to_user_id)
    if target is None or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Assignee not found")
    if target.role not in _REVIEWER_ROLES:
        raise HTTPException(
            status_code=422,
            detail="Assignee must be compliance, admin, or owner.",
        )
    return target


def _append_event(
    db: Session,
    escalation: Escalation,
    *,
    actor: User,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
) -> None:
    db.add(
        EscalationEvent(
            tenant_id=escalation.tenant_id,
            escalation_id=escalation.id,
            actor_user_id=actor.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            note=note,
        )
    )


def _out(row: Escalation) -> EscalationOut:
    decision = row.decision
    return EscalationOut(
        id=row.id,
        decision_id=row.decision_id,
        client_id=row.client_id,
        question=decision.question if decision else None,
        decision_outcome=decision.outcome if decision else None,
        decision_created_at=decision.created_at.isoformat() if decision else None,
        grounding_score=decision.grounding_score if decision else None,
        latency_ms=decision.latency_ms if decision else None,
        status=row.status,
        priority=row.priority,
        reason=row.reason,
        note=row.note,
        assigned_role=row.assigned_role,
        assigned_to_user_id=row.assigned_to_user_id,
        created_by_user_id=row.created_by_user_id,
        sla_due_at=row.sla_due_at.isoformat(),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        events=[
            EscalationEventOut(
                id=event.id,
                action=event.action,
                actor_user_id=event.actor_user_id,
                from_status=event.from_status,
                to_status=event.to_status,
                note=event.note,
                created_at=event.created_at.isoformat(),
            )
            for event in sorted(row.events, key=lambda item: item.created_at)
        ],
    )
