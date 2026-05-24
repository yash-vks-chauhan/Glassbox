from fastapi import APIRouter, Depends

from app.core.auth.deps import require_role
from app.core.openrouter_status import openrouter_status
from app.models_db import User


router = APIRouter(tags=["llm"])


@router.get("/llm/status")
def llm_status(
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, object]:
    return openrouter_status()
