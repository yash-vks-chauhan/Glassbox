from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.orchestrator import run_ask
from app.db import get_db
from app.schemas import AskRequest, AskResponse


router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    return run_ask(
        question=request.question,
        client_id=request.client_id,
        byo_key=request.byo_key,
        db=db,
    )
