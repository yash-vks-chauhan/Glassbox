"""Threads: persistent conversations about one client.

A thread is a list of decisions sharing ``thread_id``. Asking in a thread
resolves follow-ups against the previous question (``app.core.conversation``)
and records both texts on the decision. A thread is "escalated" while any of
its decisions has an open escalation.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.conversation import contextualize
from app.core.escalations import ACTIVE_STATUSES, escalation_brief
from app.core.trust_metrics import token_overlap_ratio
from app.models_db import Decision, Escalation, Thread, User, utcnow
from app.schemas import Citation, ThreadDetail, ThreadMessage, ThreadOut, Trust


TENANT_WIDE_ROLES = frozenset({"compliance", "admin", "owner"})
_TITLE_MAX = 80


def _title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1].rstrip() + "…"


def scoped_threads(user: User) -> Select:
    """Threads the user may see: reviewers see the tenant's, advisors their own."""
    stmt = select(Thread).where(Thread.tenant_id == user.tenant_id)
    if user.role not in TENANT_WIDE_ROLES:
        stmt = stmt.where(Thread.created_by_user_id == user.id)
    return stmt


def get_visible_thread(db: Session, user: User, thread_id: str) -> Thread:
    thread = db.scalar(scoped_threads(user).where(Thread.id == thread_id))
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


def prepare_thread_for_ask(
    db: Session, *, user: User, client_id: str, thread_id: str | None, question: str
) -> tuple[Thread, str]:
    """Return the thread to ask in (a new one when ``thread_id`` is None) and
    the question to answer: the advisor's text, or for a follow-up the
    context-resolved version of it. Nothing is committed here; the decision
    write commits the thread with it."""
    now = utcnow()
    if thread_id is None:
        thread = Thread(
            tenant_id=user.tenant_id,
            client_id=client_id,
            created_by_user_id=user.id,
            title=_title(question),
            status="open",
            created_at=now,
            updated_at=now,
        )
        db.add(thread)
        db.flush()
        return thread, question

    thread = db.scalar(
        select(Thread).where(Thread.tenant_id == user.tenant_id, Thread.id == thread_id)
    )
    # Only the advisor who started a thread asks in it; anyone else gets the
    # same 404 as for a thread that doesn't exist.
    if thread is None or thread.created_by_user_id != user.id:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This thread is about client {thread.client_id}.",
        )
    previous = db.scalar(
        select(Decision)
        .where(Decision.thread_id == thread.id)
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    )
    previous_question = (previous.retrieval_question or previous.question) if previous else None
    if thread.status == "resolved":
        thread.status = "open"  # a new question reopens the conversation
    thread.updated_at = now
    return thread, contextualize(question, previous_question)


def refresh_thread_status(db: Session, thread_id: str | None) -> None:
    """Escalated while any decision in the thread has an open escalation;
    back to open once none does. Resolved threads stay resolved."""
    if not thread_id:
        return
    thread = db.get(Thread, thread_id)
    if thread is None:
        return
    active = db.scalar(
        select(func.count(Escalation.id))
        .join(Decision, Decision.id == Escalation.decision_id)
        .where(Decision.thread_id == thread_id, Escalation.status.in_(ACTIVE_STATUSES))
    )
    if active:
        thread.status = "escalated"
    elif thread.status == "escalated":
        thread.status = "open"


def update_thread(
    db: Session, *, user: User, thread: Thread, status_value: str | None, title: str | None
) -> Thread:
    if thread.created_by_user_id != user.id and user.role not in TENANT_WIDE_ROLES:
        raise HTTPException(status_code=403, detail="Only the thread owner or a reviewer can change it.")
    if status_value:
        thread.status = status_value
    if title:
        thread.title = _title(title)
    thread.updated_at = utcnow()
    db.commit()
    db.refresh(thread)
    return thread


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.isoformat()


def thread_summaries(db: Session, threads: list[Thread]) -> list[ThreadOut]:
    ids = [t.id for t in threads]
    latest: dict[str, Decision] = {}
    counts: dict[str, int] = {}
    if ids:
        for decision in db.scalars(
            select(Decision)
            .where(Decision.thread_id.in_(ids))
            .order_by(Decision.created_at.asc(), Decision.id.asc())
        ):
            counts[decision.thread_id] = counts.get(decision.thread_id, 0) + 1
            latest[decision.thread_id] = decision
    return [
        ThreadOut(
            id=t.id,
            client_id=t.client_id,
            title=t.title,
            status=t.status,
            created_by_user_id=t.created_by_user_id,
            created_at=_iso(t.created_at),
            updated_at=_iso(t.updated_at),
            message_count=counts.get(t.id, 0),
            last_question=latest[t.id].question if t.id in latest else None,
            last_outcome=latest[t.id].outcome if t.id in latest else None,
        )
        for t in threads
    ]


def _citations(decision: Decision) -> list[Citation]:
    """Rebuild the citations shown with the answer: for each kept claim, the
    retrieved passage of its cited source that best matches the claim."""
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for claim in decision.claims:
        if not claim.kept or not claim.cited_source_id:
            continue
        passages = [c for c in decision.retrieved_chunks if c.source_id == claim.cited_source_id]
        if not passages:
            continue
        best = max(passages, key=lambda c: token_overlap_ratio(claim.claim_text, c.chunk_text))
        key = (best.source_id, best.chunk_text)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                source_id=best.source_id,
                source_type=best.source_type,
                snippet=best.chunk_text[:600],
            )
        )
    return citations


def thread_detail(db: Session, thread: Thread) -> ThreadDetail:
    decisions = db.scalars(
        select(Decision)
        .where(Decision.thread_id == thread.id)
        .options(selectinload(Decision.claims), selectinload(Decision.retrieved_chunks))
        .order_by(Decision.created_at.asc(), Decision.id.asc())
    ).all()
    escalations: dict[str, Escalation] = {}
    if decisions:
        for escalation in db.scalars(
            select(Escalation)
            .where(
                Escalation.decision_id.in_([d.id for d in decisions]),
                Escalation.status.in_(ACTIVE_STATUSES),
            )
            .order_by(Escalation.created_at.asc())
        ):
            escalations[escalation.decision_id] = escalation
    summary = thread_summaries(db, [thread])[0]
    return ThreadDetail(
        **summary.model_dump(),
        messages=[
            ThreadMessage(
                decision_id=d.id,
                created_at=_iso(d.created_at),
                question=d.question,
                retrieval_question=d.retrieval_question,
                outcome=d.outcome,
                answer=d.final_answer,
                refusal_reason=d.refusal_reason,
                citations=_citations(d),
                trust=Trust(
                    grounding_score=d.grounding_score,
                    model_route=d.llm_model,
                    total_ms=d.latency_ms,
                ),
                escalation=escalation_brief(escalations.get(d.id)),
            )
            for d in decisions
        ],
    )
