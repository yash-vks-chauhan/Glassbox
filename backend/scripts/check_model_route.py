from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from app.core.llm import LLMUnavailable, chat
from app.core.model_router import prompt_profile_for_route, route_from_spec, route_health


DEFAULT_PROMPT = (
    "Return one short JSON object with keys status and summary. "
    "Use status='ok' and say this is a GlassBox model route probe."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check one GlassBox model route without requiring production approval."
    )
    parser.add_argument(
        "--route",
        required=True,
        help="Route spec, for example vllm:Qwen/Qwen2.5-7B-Instruct or openrouter:<paid-model-id>.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Small probe prompt to send through the route.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Only check provider/model health; do not send a chat completion.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    route = route_from_spec(args.route)
    profile = prompt_profile_for_route(route)
    result: dict[str, Any] = {
        "route": route.spec,
        "provider": route.provider,
        "model": route.model,
        "configured": route.configured,
        "production_eligible": route.production_eligible,
        "blocked_reason": route.blocked_reason,
        "prompt_profile": profile.__dict__,
        "health": route_health(route),
        "chat": None,
    }

    if not args.skip_chat:
        started = time.perf_counter()
        try:
            text = chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a route probe. Return only compact JSON. "
                            "Do not include markdown."
                        ),
                    },
                    {"role": "user", "content": args.prompt},
                ],
                temperature=0,
                model=route.spec,
                enforce_production_gate=False,
            )
            result["chat"] = {
                "ok": True,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "sample": text[:1000],
            }
        except LLMUnavailable as exc:
            result["chat"] = {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc),
            }

    print(json.dumps(result, indent=2, sort_keys=True))
    health_ok = bool(result["health"].get("healthy")) and bool(result["health"].get("available"))
    chat_ok = args.skip_chat or bool((result.get("chat") or {}).get("ok"))
    return 0 if health_ok and chat_ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
