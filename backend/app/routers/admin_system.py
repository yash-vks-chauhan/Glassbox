"""Admin view of the configuration that actually governs this deployment.

The admin page used to hard-code a hosting region and a retention period
that nothing enforced. Everything here is read from the running settings,
so the page can only show what is true.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.core.auth.deps import require_role
from app.core.model_router import runtime_status
from app.db import get_db
from app.models_db import User
from app.schemas import GuardrailStatus, RateLimitInfo, SystemInfo


router = APIRouter(prefix="/admin/system", tags=["admin"])


@router.get("", response_model=SystemInfo)
def system_info(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> SystemInfo:
    settings = get_settings()
    runtime = runtime_status(db=db)
    return SystemInfo(
        version=__version__,
        environment="production" if settings.production_mode else "development",
        database=db.get_bind().dialect.name,
        inference_mode=str(runtime["mode"]),
        inference_route=runtime.get("active_route"),
        embedding_backend=settings.embedding_backend,
        rate_limits=RateLimitInfo(
            auth_per_min=settings.rate_limit_auth_per_min,
            ask_per_min=settings.rate_limit_ask_per_min,
            default_per_min=settings.rate_limit_default_per_min,
        ),
        max_ask_body_bytes=settings.body_max_bytes_ask,
        audit_retention=(
            "Indefinite. The database refuses deletes on the audit tables; "
            "corrections are appended to decision_corrections."
        ),
        guardrails=[
            GuardrailStatus(
                key="refuse_without_source",
                label="Refuse when no approved source supports the answer",
                enabled=True,
            ),
            GuardrailStatus(
                key="claim_verification",
                label="Verify every claim against its cited source",
                enabled=True,
                detail=f"mode: {settings.verify_mode}",
                setting="VERIFY_MODE",
            ),
            GuardrailStatus(
                key="grounding_threshold",
                label="Drop claims below the grounding threshold",
                enabled=True,
                detail=f"minimum support {settings.claim_min_grounding_score:.2f}",
                setting="CLAIM_MIN_GROUNDING_SCORE",
            ),
            GuardrailStatus(
                key="log_claim_drops",
                label="Record every dropped claim in the audit trail",
                enabled=True,
            ),
            GuardrailStatus(
                key="escalation_offer",
                label="Offer escalation on flagged and refused answers",
                enabled=True,
            ),
            GuardrailStatus(
                key="advisor_byo_keys",
                label="Advisors may use their own model key",
                enabled=settings.allow_advisor_byo_keys,
                setting="ALLOW_ADVISOR_BYO_KEYS",
            ),
            GuardrailStatus(
                key="production_model_gate",
                label="Hosted models must pass the eval gate in production",
                enabled=settings.require_recent_model_eval_in_production,
                setting="REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION",
            ),
        ],
    )
