"""Threads: GET /threads, GET /threads/{id}, PATCH /threads/{id}."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.deps import current_user
from app.core.threads import (
    get_visible_thread,
    scoped_threads,
    thread_detail,
    thread_summaries,
    update_thread,
)
from app.db import get_db
from app.models_db import Thread, User
from app.schemas import ThreadDetail, ThreadOut, ThreadUpdateRequest


router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=list[ThreadOut])
def list_threads(
    client_id: str | None = Query(default=None, max_length=64),
    status: Literal["open", "resolved", "escalated"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ThreadOut]:
    """Most recently active first. Advisors see their own threads; reviewers
    see the workspace's."""
    stmt = scoped_threads(user)
    if client_id:
        stmt = stmt.where(Thread.client_id == client_id.upper())
    if status:
        stmt = stmt.where(Thread.status == status)
    threads = db.scalars(stmt.order_by(Thread.updated_at.desc()).limit(limit)).all()
    return thread_summaries(db, list(threads))


@router.get("/{thread_id}", response_model=ThreadDetail)
def get_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ThreadDetail:
    return thread_detail(db, get_visible_thread(db, user, thread_id))


@router.patch("/{thread_id}", response_model=ThreadOut)
def patch_thread(
    thread_id: str,
    payload: ThreadUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ThreadOut:
    thread = get_visible_thread(db, user, thread_id)
    updated = update_thread(
        db, user=user, thread=thread, status_value=payload.status, title=payload.title
    )
    return thread_summaries(db, [updated])[0]
