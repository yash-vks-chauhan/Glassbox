"""Unauthenticated endpoints used by the marketing site.

They sit in the strict rate-limit tier (see ``classify_route``) and accept
only small, strictly validated bodies.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth.email import get_email_service
from app.db import get_db
from app.models_db import AccessRequest
from app.schemas import AccessRequestCreate, AccessRequestReceived


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/public", tags=["public"])


@router.post(
    "/access-requests",
    response_model=AccessRequestReceived,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_access_request(
    payload: AccessRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> AccessRequestReceived:
    # Honeypot hit: answer exactly like a real submission so bots learn
    # nothing, but store and send nothing.
    if payload.website:
        return AccessRequestReceived()

    row = AccessRequest(
        name=payload.name.strip(),
        company=payload.company.strip(),
        work_email=str(payload.work_email),
        role=payload.role.strip(),
        message=(payload.message or "").strip() or None,
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )
    db.add(row)
    db.commit()

    notify = get_settings().access_request_notify_email
    if notify:
        try:
            get_email_service().send(
                to=notify,
                subject=f"GlassBox access request: {row.company}",
                body_text=(
                    f"Name: {row.name}\n"
                    f"Role: {row.role}\n"
                    f"Firm: {row.company}\n"
                    f"Email: {row.work_email}\n\n"
                    f"{row.message or '(no message)'}\n\n"
                    f"Request id: {row.id}\n"
                ),
            )
        except Exception:  # noqa: BLE001 — the request is already stored
            logger.exception("access_request_notify_failed id=%s", row.id)
    return AccessRequestReceived()
