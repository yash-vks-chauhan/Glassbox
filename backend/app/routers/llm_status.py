from fastapi import APIRouter

from app.core.openrouter_status import openrouter_status


router = APIRouter(tags=["llm"])


@router.get("/llm/status")
def llm_status() -> dict[str, object]:
    return openrouter_status()
