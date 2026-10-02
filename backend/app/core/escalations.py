"""Escalation helpers shared by the escalation and review endpoints."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models_db import Escalation, EscalationEvent, User
from app.schemas import EscalationBrief


ACTIVE_STATUSES = ("open", "in_review")
# Reviewers have four hours to pick up an escalation.
ESCALATION_SLA = timedelta(hours=4)


def append_event(
    db: Session,
    escalation: Escalation,
    *,
    actor: User,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
) -> None:
    """Add an entry to the escalation's activity history."""
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


def escalation_brief(escalation: Escalation | None) -> EscalationBrief | None:
    if escalation is None:
        return None
    return EscalationBrief(
        id=escalation.id,
        status=escalation.status,
        priority=escalation.priority,
        sla_due_at=escalation.sla_due_at.isoformat(),
        assigned_to_user_id=escalation.assigned_to_user_id,
    )
