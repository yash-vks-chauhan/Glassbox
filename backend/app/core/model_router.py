from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.model_approval import route_eval_approval


class LLMUnavailable(RuntimeError):
    pass


class ProductionModelNotApproved(LLMUnavailable):
    pass


PLACEHOLDER_OPENROUTER_KEYS = {
    "sk-or-...",
    "sk-or-your-key",
    "sk-or-your-key-here",
    "your-openrouter-key",
}


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    label: str
    base_url: str | None = None
    configured: bool = True
    production_eligible: bool = True
    blocked_reason: str | None = None
    api_key: str | None = None

    @property
    def spec(self) -> str:
        if self.provider == "local":
            return "local:glassbox-deterministic"
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ModelPromptProfile:
    route: str
    temperature: float
    max_output_tokens: int
    json_mode: bool
    streaming: bool


_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def has_usable_openrouter_key(key: str | None) -> bool:
    normalized = (key or "").strip()
    if not normalized:
        return False
    if normalized.lower() in PLACEHOLDER_OPENROUTER_KEYS:
        return False
    return normalized.startswith("sk-or-") and len(normalized) > 16


def chat_with_router(
    messages: list[dict[str, str]],
    *,
    local_chat,
    temperature: float | None = None,
    model: str | None = None,
    api_key: str | None = None,
    enforce_production_gate: bool = True,
) -> str:
    settings = get_settings()
    errors: list[str] = []
    for route in routes_for_chat(model_override=model, api_key=api_key):
        if not route.configured:
            errors.append(f"{route.label}: not configured")
            continue
        if settings.production_mode and enforce_production_gate and not route.production_eligible:
            errors.append(f"{route.label}: {route.blocked_reason or 'blocked'}")
            continue
        if settings.production_mode and enforce_production_gate:
            approval = route_eval_approval(route.spec)
            if not approval["approved"]:
                errors.append(f"{route.label}: model eval gate failed: {approval['reason']}")
                continue
        try:
            if route.provider == "local":
                return str(local_chat(messages)).strip()
            if route.provider == "openrouter":
                return _openai_compatible_chat(
                    route=route,
                    messages=messages,
                    temperature=temperature,
                    auth_header=f"Bearer {route.api_key or ''}",
                    extra_headers={"X-Title": "GlassBox"},
                )
            if route.provider == "ollama":
                return _ollama_chat(route, messages, temperature)
            if route.provider == "vllm":
                return _openai_compatible_chat(
                    route=route,
                    messages=messages,
                    temperature=temperature,
                    auth_header=f"Bearer {route.api_key}" if route.api_key else None,
                )
            errors.append(f"{route.label}: unsupported provider")
        except LLMUnavailable as exc:
            errors.append(f"{route.label}: {exc}")
    raise LLMUnavailable("; ".join(errors) or "No model routes were available")


def routes_for_chat(
    model_override: str | None = None,
    api_key: str | None = None,
) -> list[ModelRoute]:
    settings = get_settings()
    if model_override:
        return [_route_from_override(model_override, api_key=api_key)]

    if settings.production_mode:
        routes = configured_routes(include_local=False)
        if api_key:
            # User-enrolled keys are provider-specific today. Put the caller's
            # OpenRouter route first, then fall through to platform candidates.
            routes = [_openrouter_route(api_key=api_key)] + [
                route for route in routes if route.provider != "openrouter"
            ]
        return routes or [_openrouter_route(api_key=api_key)]

    if settings.local_llm and not api_key:
        return [_local_route()]

    routes: list[ModelRoute] = []
    for provider in settings.router_providers:
        if provider == "openrouter":
            routes.append(_openrouter_route(api_key=api_key))
        elif provider == "ollama":
            routes.append(_ollama_route())
        elif provider == "vllm":
            routes.append(_vllm_route())
        elif provider == "local":
            routes.append(_local_route())

    if not any(route.provider == "openrouter" for route in routes) and api_key:
        routes.append(_openrouter_route(api_key=api_key))
    return routes or [_openrouter_route(api_key=api_key)]


def configured_routes(include_local: bool = True) -> list[ModelRoute]:
    settings = get_settings()
    if settings.candidate_route_ids:
        routes = [_route_from_override(route) for route in settings.candidate_route_ids]
    else:
        routes = [_ollama_route(), _vllm_route(), _openrouter_route()]
    if include_local:
        routes.append(_local_route())
    return routes


def route_from_spec(route_spec: str) -> ModelRoute:
    return _route_from_override(route_spec)


def route_health(route: ModelRoute | str) -> dict[str, Any]:
    if isinstance(route, str):
        route = _route_from_override(route)
    return _cached_health(route)


def provider_health() -> list[dict[str, Any]]:
    return [_cached_health(route) for route in configured_routes(include_local=True)]


def production_model_status(db: Session | None = None) -> dict[str, Any]:
    settings = get_settings()
    routes = configured_routes(include_local=False)
    route_rows: list[dict[str, Any]] = []
    approved_routes: list[str] = []

    for route in routes:
        approval = route_eval_approval(route.spec, db=db)
        approved_for_inference = (
            route.configured
            and route.production_eligible
            and bool(approval.get("approved"))
        )
        if approved_for_inference:
            approved_routes.append(route.spec)
        route_rows.append(
            {
                "provider": route.provider,
                "label": route.label,
                "model": route.model,
                "route": route.spec,
                "configured": route.configured,
                "production_eligible": route.production_eligible,
                "blocked_reason": route.blocked_reason,
                "approved_for_inference": approved_for_inference,
                "approval": approval,
                "prompt_profile": prompt_profile_for_route(route).__dict__,
            }
        )

    product_inference_allowed = bool(settings.production_mode and approved_routes)
    blocked_reason = None
    if settings.production_mode and not approved_routes:
        blocked_reason = (
            "No approved production model is active. Run the full model eval gate "
            f"({settings.eval_min_questions_for_production} cases) for a configured "
            "candidate route, then promote that route."
        )
    elif not settings.production_mode:
        blocked_reason = "Production mode is disabled."

    return {
        "production_mode": settings.production_mode,
        "product_inference_allowed": product_inference_allowed,
        "active_route": approved_routes[0] if product_inference_allowed else None,
        "candidate_routes": [route.spec for route in routes],
        "approved_routes": approved_routes,
        "required_eval_questions": settings.eval_min_questions_for_production,
        "eval_freshness_hours": settings.model_eval_freshness_hours,
        "require_recent_eval": settings.require_recent_model_eval_in_production,
        "approved_models_env": f"APPROVED_MODELS={','.join(approved_routes)}",
        "blocked_reason": blocked_reason,
        "routes": route_rows,
    }


def ensure_production_model_ready(db: Session | None = None) -> None:
    settings = get_settings()
    if not settings.production_mode:
        return
    status = production_model_status(db=db)
    if not status["product_inference_allowed"]:
        raise ProductionModelNotApproved(str(status["blocked_reason"]))


def prompt_profile_for_route(route: ModelRoute | str) -> ModelPromptProfile:
    settings = get_settings()
    if isinstance(route, str):
        route = _route_from_override(route)
    return ModelPromptProfile(
        route=route.spec,
        temperature=0.0,
        max_output_tokens=settings.llm_max_output_tokens,
        json_mode=route.provider in {"openrouter", "vllm", "ollama", "local"},
        streaming=route.provider in {"openrouter", "vllm", "ollama"},
    )


def _route_from_override(model_override: str, api_key: str | None = None) -> ModelRoute:
    provider, sep, raw_model = model_override.partition(":")
    provider = provider.strip().lower()
    if sep and provider in {"openrouter", "ollama", "vllm", "local"}:
        if provider == "openrouter":
            return _openrouter_route(model=raw_model, api_key=api_key)
        if provider == "ollama":
            return _ollama_route(model=raw_model)
        if provider == "vllm":
            return _vllm_route(model=raw_model)
        return _local_route()
    if model_override in {"local", "glassbox-local", "glassbox-deterministic"}:
        return _local_route()
    return _openrouter_route(model=model_override, api_key=api_key)


def _openrouter_route(
    model: str | None = None, api_key: str | None = None
) -> ModelRoute:
    settings = get_settings()
    route_model = model or settings.llm_model
    key = api_key or settings.openrouter_api_key
    configured = has_usable_openrouter_key(key)
    blocked_reason = None
    production_eligible = True
    if settings.production_mode and route_model.endswith(":free"):
        if not settings.allow_openrouter_free_in_production:
            production_eligible = False
            blocked_reason = "free OpenRouter models are disabled in product mode"
    if settings.production_mode and settings.approved_model_ids:
        if f"openrouter:{route_model}" not in settings.approved_model_ids:
            production_eligible = False
            blocked_reason = "model is not in APPROVED_MODELS"
    return ModelRoute(
        provider="openrouter",
        model=route_model,
        label="OpenRouter",
        base_url=settings.llm_base_url.rstrip("/"),
        configured=configured,
        production_eligible=production_eligible,
        blocked_reason=blocked_reason,
        api_key=key,
    )


def _ollama_route(model: str | None = None) -> ModelRoute:
    settings = get_settings()
    route_model = model or settings.ollama_model
    production_eligible = True
    blocked_reason = None
    if settings.production_mode and settings.approved_model_ids:
        if f"ollama:{route_model}" not in settings.approved_model_ids:
            production_eligible = False
            blocked_reason = "model is not in APPROVED_MODELS"
    return ModelRoute(
        provider="ollama",
        model=route_model,
        label="Ollama",
        base_url=settings.ollama_base_url.rstrip("/"),
        production_eligible=production_eligible,
        blocked_reason=blocked_reason,
    )


def _vllm_route(model: str | None = None) -> ModelRoute:
    settings = get_settings()
    route_model = model or settings.vllm_model
    production_eligible = True
    blocked_reason = None
    if settings.production_mode and settings.approved_model_ids:
        if f"vllm:{route_model}" not in settings.approved_model_ids:
            production_eligible = False
            blocked_reason = "model is not in APPROVED_MODELS"
    return ModelRoute(
        provider="vllm",
        model=route_model,
        label="vLLM",
        base_url=settings.vllm_base_url.rstrip("/"),
        production_eligible=production_eligible,
        blocked_reason=blocked_reason,
    )


def _local_route() -> ModelRoute:
    return ModelRoute(
        provider="local",
        model="glassbox-deterministic",
        label="GlassBox deterministic fallback",
        base_url=None,
        configured=True,
        production_eligible=False,
        blocked_reason="deterministic fallback is for demo or outage handling, not primary product inference",
    )


def _openai_compatible_chat(
    *,
    route: ModelRoute,
    messages: list[dict[str, str]],
    temperature: float | None,
    auth_header: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    settings = get_settings()
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if auth_header:
        headers["Authorization"] = auth_header
    payload = {
        "model": route.model,
        "messages": messages,
        "temperature": temperature if temperature is not None else prompt_profile_for_route(route).temperature,
        "max_tokens": settings.llm_max_output_tokens,
    }
    data = _post_json(
        f"{route.base_url}/chat/completions",
        headers=headers,
        json=payload,
    )
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"{route.provider} returned an unexpected payload") from exc


def _ollama_chat(
    route: ModelRoute, messages: list[dict[str, str]], temperature: float | None
) -> str:
    settings = get_settings()
    payload = {
        "model": route.model,
        "messages": messages,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {
            "temperature": temperature
            if temperature is not None
            else prompt_profile_for_route(route).temperature,
            "num_predict": settings.llm_max_output_tokens,
        },
    }
    data = _post_json(f"{route.base_url}/api/chat", json=payload)
    try:
        return str(data["message"]["content"]).strip()
    except (KeyError, TypeError) as exc:
        raise LLMUnavailable("Ollama returned an unexpected payload") from exc


def _post_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    attempts = max(settings.llm_max_retries, 0) + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=json)
                if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                raise LLMUnavailable("provider returned a non-object payload")
        except (httpx.HTTPError, ValueError, LLMUnavailable) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(settings.llm_retry_backoff_seconds * (attempt + 1))
    raise LLMUnavailable(str(last_error) if last_error else "provider request failed")


def _health(route: ModelRoute) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "provider": route.provider,
        "label": route.label,
        "model": route.model,
        "route": route.spec,
        "configured": route.configured,
        "healthy": False,
        "available": False,
        "production_eligible": route.production_eligible,
        "blocked_reason": route.blocked_reason,
        "latency_ms": None,
        "error": None,
        "prompt_profile": prompt_profile_for_route(route).__dict__,
    }
    if not route.configured:
        result["error"] = "not configured"
        return result
    try:
        if route.provider == "local":
            result["healthy"] = True
            result["available"] = True
        elif route.provider == "openrouter":
            models = _fetch_openai_models(route)
            result["healthy"] = True
            result["available"] = route.model in models or route.model == "openrouter/free"
        elif route.provider == "ollama":
            models = _fetch_ollama_models(route)
            result["healthy"] = True
            result["available"] = route.model in models
        elif route.provider == "vllm":
            models = _fetch_openai_models(route)
            result["healthy"] = True
            result["available"] = not models or route.model in models
    except Exception as exc:
        result["error"] = str(exc)
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def _cached_health(route: ModelRoute) -> dict[str, Any]:
    settings = get_settings()
    cached = _HEALTH_CACHE.get(route.spec)
    if cached and time.time() - cached[0] <= settings.model_health_cache_ttl_seconds:
        return dict(cached[1])
    result = _health(route)
    _HEALTH_CACHE[route.spec] = (time.time(), result)
    return dict(result)


def _fetch_openai_models(route: ModelRoute) -> set[str]:
    headers = {}
    if route.provider == "openrouter" and route.api_key:
        headers["Authorization"] = f"Bearer {route.api_key}"
    with httpx.Client(timeout=min(get_settings().llm_timeout_seconds, 5.0)) as client:
        response = client.get(f"{route.base_url}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data", payload)
    if not isinstance(data, list):
        return set()
    return {str(item.get("id")) for item in data if isinstance(item, dict)}


def _fetch_ollama_models(route: ModelRoute) -> set[str]:
    with httpx.Client(timeout=min(get_settings().llm_timeout_seconds, 5.0)) as client:
        response = client.get(f"{route.base_url}/api/tags")
        response.raise_for_status()
        payload = response.json()
    models = payload.get("models", [])
    if not isinstance(models, list):
        return set()
    return {str(item.get("name")) for item in models if isinstance(item, dict)}
