from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.core.model_approval import approved_model_routes, route_eval_approval
from app.core.model_router import route_from_spec
from app.db import SessionLocal, init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote a model route only if its latest persisted full eval passes "
            "the production approval gate."
        )
    )
    parser.add_argument(
        "--route",
        required=True,
        help="Route spec to promote, for example vllm:Qwen/Qwen2.5-7B-Instruct.",
    )
    parser.add_argument(
        "--write-env-file",
        help="Optional .env file to update with the computed APPROVED_MODELS value.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable JSON instead of a short text report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    route = route_from_spec(args.route)
    if route.provider == "local":
        payload = {
            "route": args.route,
            "approved": False,
            "approval": {
                "approved": False,
                "reason": "deterministic local fallback cannot be promoted for production inference",
                "run_id": None,
                "created_at": None,
            },
            "message": "Route was not promoted because local fallback is not a production model.",
        }
        _print(payload, json_output=args.json_output, error=True)
        return 2

    init_db()
    with SessionLocal() as db:
        approval = route_eval_approval(args.route, db=db)
        if not approval["approved"]:
            payload = {
                "route": args.route,
                "approved": False,
                "approval": approval,
                "message": "Route was not promoted because the production eval gate did not pass.",
            }
            _print(payload, json_output=args.json_output, error=True)
            return 2

        current_env_routes = set(get_settings().approved_model_ids)
        persisted_approved_routes = set(approved_model_routes(db))
        approved = sorted(
            item
            for item in current_env_routes | persisted_approved_routes | {args.route}
            if route_from_spec(item).provider != "local"
        )
        env_line = f"APPROVED_MODELS={','.join(approved)}"
        if args.write_env_file:
            _write_env_line(Path(args.write_env_file), env_line)

        payload = {
            "route": args.route,
            "approved": True,
            "approval": approval,
            "approved_models": approved,
            "env": env_line,
            "write_env_file": args.write_env_file,
            "message": "Route is approved for production inference.",
        }
        _print(payload, json_output=args.json_output)
        return 0


def _print(payload: dict[str, Any], *, json_output: bool, error: bool = False) -> None:
    target = sys.stderr if error else sys.stdout
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True), file=target)
        return
    print(payload["message"], file=target)
    print(f"route={payload['route']}", file=target)
    print(f"reason={payload['approval']['reason']}", file=target)
    if payload.get("env"):
        print(payload["env"], file=target)


def _write_env_line(path: Path, env_line: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("APPROVED_MODELS="):
            updated.append(env_line)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(env_line)
    path.write_text("\n".join(updated) + "\n")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
