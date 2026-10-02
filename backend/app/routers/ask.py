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
from app.core.model_router import (
    ProductionModelNotApproved,
    ensure_production_model_ready,
    runtime_status,
)
from app.core.orchestrator import run_ask, run_ask_events
from app.core.threads import prepare_thread_for_ask
from app.db import get_db
from app.models_db import ClientRecord, User
from app.routers.byo_keys import byo_keys_allowed, load_byo_key_for_user
from app.schemas import AskRequest, AskResponse, AskRuntimeStatus


router = APIRouter(tags=["ask"])

_ASK_ROLES = ("advisor", "compliance", "admin", "owner")

# Provider the orchestrator routes through when a user-supplied key is
# present. We standardise on a single name today (the only LLM provider that
# meaningfully accepts BYO is OpenRouter); broader fan-out plugs in here.
_BYO_PROVIDER = "openrouter"


def _byo_key_for(db: Session, user: User) -> str | None:
    if not byo_keys_allowed(user):
        return None
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


@router.get("/ask/runtime-status", response_model=AskRuntimeStatus)
def ask_runtime_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ASK_ROLES)),
) -> dict:
    return runtime_status(api_key=_byo_key_for(db, user), db=db)


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ASK_ROLES)),
) -> AskResponse:
    client_id = _validated_client_id(db, user, request.client_id)
    try:
        ensure_production_model_ready(db)
        thread, question = prepare_thread_for_ask(
            db, user=user, client_id=client_id, thread_id=request.thread_id,
            question=request.question,
        )
        response = run_ask(
            question=question,
            asked_question=request.question,
            thread_id=thread.id,
            client_id=client_id,
            byo_key=_byo_key_for(db, user),
            db=db,
            allow_fallback=not get_settings().production_mode,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        return _with_thread(response, thread.id, request.question, question)
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
    # Resolve the thread before streaming so a bad thread id is a plain 404.
    thread, question = prepare_thread_for_ask(
        db, user=user, client_id=client_id, thread_id=request.thread_id,
        question=request.question,
    )
    return StreamingResponse(
        _sse_events(request, db, user, client_id, thread.id, question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_events(
    request: AskRequest,
    db: Session,
    user: User,
    client_id: str,
    thread_id: str,
    question: str,
) -> Iterator[str]:
    try:
        for event in run_ask_events(
            question=question,
            asked_question=request.question,
            thread_id=thread_id,
            client_id=client_id,
            byo_key=_byo_key_for(db, user),
            db=db,
            allow_fallback=not get_settings().production_mode,
            tenant_id=user.tenant_id,
            user_id=user.id,
        ):
            data = event.get("data", {})
            if event["event"] == "final" and isinstance(data, AskResponse):
                data = _with_thread(data, thread_id, request.question, question)
            yield _format_sse(event["event"], data)
    except Exception as exc:
        yield _format_sse("error", {"message": str(exc)})


def _with_thread(
    response: AskResponse, thread_id: str, asked: str, resolved: str
) -> AskResponse:
    response.thread_id = thread_id
    response.retrieval_question = resolved if resolved != asked else None
    return response


def _format_sse(event: str, data: object) -> str:
    payload = json.dumps(jsonable_encoder(data), separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
