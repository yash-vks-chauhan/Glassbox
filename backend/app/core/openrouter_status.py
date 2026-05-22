from __future__ import annotations

import httpx

from app.config import get_settings
from app.core.llm import has_usable_openrouter_key


RECOMMENDED_FAMILIES = ("llama", "qwen", "deepseek", "gemma", "mistral")


def openrouter_status() -> dict[str, object]:
    settings = get_settings()
    status: dict[str, object] = {
        "local_llm": settings.local_llm,
        "configured_model": settings.llm_model,
        "has_openrouter_key": has_usable_openrouter_key(settings.openrouter_api_key),
        "models_endpoint_reachable": False,
        "configured_model_available": None,
        "recommended_free_models": [],
    }
    try:
        models = fetch_models()
    except Exception as exc:
        status["error"] = str(exc)
        return status

    model_ids = {model.get("id", "") for model in models}
    status["models_endpoint_reachable"] = True
    status["configured_model_available"] = (
        True
        if settings.llm_model == "openrouter/free"
        else settings.llm_model in model_ids
    )
    status["recommended_free_models"] = recommended_free_models(models)
    return status


def fetch_models() -> list[dict[str, object]]:
    settings = get_settings()
    url = f"{settings.llm_base_url.rstrip('/')}/models"
    with httpx.Client(timeout=10) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data", payload)
    return data if isinstance(data, list) else []


def recommended_free_models(models: list[dict[str, object]]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for model in models:
        model_id = str(model.get("id", ""))
        name = str(model.get("name", ""))
        if not _is_free_model(model_id, name, model.get("pricing")):
            continue
        haystack = f"{model_id} {name}".lower()
        if not any(family in haystack for family in RECOMMENDED_FAMILIES):
            continue
        matches.append({"id": model_id, "name": name})
    return sorted(matches, key=lambda item: item["id"])[:50]


def _is_free_model(model_id: str, name: str, pricing: object) -> bool:
    if model_id.endswith(":free") or "(free)" in name.lower():
        return True
    if not isinstance(pricing, dict):
        return False
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    return str(prompt) in {"0", "0.0"} and str(completion) in {"0", "0.0"}
