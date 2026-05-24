import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth.deps import require_role
from app.core.llm import LLMUnavailable
from app.core.model_router import ProductionModelNotApproved, ensure_production_model_ready
from app.core.orchestrator import run_ask, run_ask_events
from app.db import get_db
from app.models_db import ClientRecord, User
from app.routers.byo_keys import load_byo_key_for_user
from app.schemas import AskRequest, AskResponse


router = APIRouter(tags=["ask"])

_ASK_ROLES = ("advisor", "compliance", "admin", "owner")

# Provider the orchestrator routes through when a user-supplied key is
# present. We standardise on a single name today (the only LLM provider that
# meaningfully accepts BYO is OpenRouter); broader fan-out plugs in here.
_BYO_PROVIDER = "openrouter"


def _byo_key_for(db: Session, user: User) -> str | None:
    return load_byo_key_for_user(db, user_id=user.id, provider=_BYO_PROVIDER)


def _validated_client_id(db: Session, user: User, client_id: str | None) -> str:
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id is required for product ask requests.",
        )
    normalized = client_id.upper()
    exists = db.scalar(
        select(ClientRecord.id).where(
            ClientRecord.tenant_id == user.tenant_id,
            ClientRecord.client_code == normalized,
        )
    )
    if exists is None:
        # 404, not 403: a caller should not learn whether another tenant has
        # this client code.
        raise HTTPException(status_code=404, detail="Client not found")
    return normalized


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ASK_ROLES)),
) -> AskResponse:
    client_id = _validated_client_id(db, user, request.client_id)
    try:
        ensure_production_model_ready(db)
        return run_ask(
            question=request.question,
            client_id=client_id,
            byo_key=_byo_key_for(db, user),
            db=db,
            allow_fallback=not get_settings().production_mode,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
    except ProductionModelNotApproved as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LLMUnavailable as exc:
        if get_settings().production_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Production model route is unavailable: {exc}",
            ) from exc
        raise


@router.post("/ask/stream")
def ask_stream(
    request: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ASK_ROLES)),
) -> StreamingResponse:
    client_id = _validated_client_id(db, user, request.client_id)
    try:
        ensure_production_model_ready(db)
    except ProductionModelNotApproved as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return StreamingResponse(
        _sse_events(request, db, user, client_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_events(request: AskRequest, db: Session, user: User, client_id: str) -> Iterator[str]:
    try:
        for event in run_ask_events(
            question=request.question,
            client_id=client_id,
            byo_key=_byo_key_for(db, user),
            db=db,
            allow_fallback=not get_settings().production_mode,
            tenant_id=user.tenant_id,
            user_id=user.id,
        ):
            yield _format_sse(event["event"], event.get("data", {}))
    except Exception as exc:
        yield _format_sse("error", {"message": str(exc)})


def _format_sse(event: str, data: object) -> str:
    payload = json.dumps(jsonable_encoder(data), separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
