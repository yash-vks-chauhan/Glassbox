from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.core.llm import LLMUnavailable, chat, has_usable_openrouter_key
from app.core.openrouter_status import openrouter_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Check OpenRouter free model wiring.")
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Also send a tiny chat request. Requires OPENROUTER_API_KEY and GLASSBOX_LOCAL_LLM=0.",
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help="Also send a full /ask request through retrieval, answer, verification, and audit logging.",
    )
    args = parser.parse_args()

    status = openrouter_status()
    print(f"local_llm={status['local_llm']}")
    print(f"configured_model={status['configured_model']}")
    print(f"has_openrouter_key={status['has_openrouter_key']}")
    print(f"models_endpoint_reachable={status['models_endpoint_reachable']}")
    print(f"configured_model_available={status['configured_model_available']}")

    models = status.get("recommended_free_models", [])
    print("recommended_free_models:")
    for model in models[:12] if isinstance(models, list) else []:
        if isinstance(model, dict):
            print(f"  - {model['id']} | {model['name']}")

    if args.chat:
        settings = get_settings()
        if settings.local_llm:
            print("chat_check=skipped GLASSBOX_LOCAL_LLM is enabled")
            return 1
        if not has_usable_openrouter_key(settings.openrouter_api_key):
            print("chat_check=skipped OPENROUTER_API_KEY is not configured")
            return 1
        try:
            response = chat([{"role": "user", "content": "Reply with exactly: connected"}])
        except LLMUnavailable as exc:
            print(f"chat_check=failed {exc}")
            return 1
        print(f"chat_check=ok response={response[:120]}")
    if args.ask:
        if get_settings().local_llm:
            print("ask_check=skipped GLASSBOX_LOCAL_LLM is enabled")
            return 1
        if not has_usable_openrouter_key(get_settings().openrouter_api_key):
            print("ask_check=skipped OPENROUTER_API_KEY is not configured")
            return 1
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            response = client.post(
                "/ask",
                json={
                    "question": "Is fund F100 suitable for client C001?",
                    "client_id": "C001",
                },
            )
        if response.status_code != 200:
            print(f"ask_check=failed status={response.status_code} body={response.text[:240]}")
            return 1
        payload = response.json()
        print(
            "ask_check=ok "
            f"outcome={payload['outcome']} "
            f"decision_id={payload['decision_id']} "
            f"citations={len(payload['citations'])}"
        )
        if payload["outcome"] == "fallback":
            print("ask_check=warning hosted LLM was unavailable and deterministic fallback handled the request")
    return 0


if __name__ == "__main__":
    sys.exit(main())
