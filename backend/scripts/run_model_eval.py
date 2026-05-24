from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.config import get_settings
from app.core.model_approval import approved_model_routes
from app.core.model_eval import evaluate_models
from app.db import SessionLocal, init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the GlassBox finance/compliance model evaluation suite."
    )
    parser.add_argument(
        "--routes",
        help="Comma-separated route specs, for example ollama:qwen2.5-coder:1.5b,local:glassbox-deterministic.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of benchmark cases to run. Defaults to the full dataset.",
    )
    parser.add_argument(
        "--gate",
        choices=["fast", "full"],
        default="full",
        help="Use the 25-case fast gate or the full approval gate.",
    )
    parser.add_argument(
        "--determinism-runs",
        type=int,
        default=2,
        help="Repeated runs per determinism probe case.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Score models without writing eval runs/results to the database.",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip corpus ingestion before scoring.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the full leaderboard payload as JSON.",
    )
    parser.add_argument(
        "--print-approved-env",
        action="store_true",
        help="Print an APPROVED_MODELS=... line from currently approved persisted runs.",
    )
    parser.add_argument(
        "--fail-on-no-production-ready",
        action="store_true",
        help="Exit with code 2 if no evaluated model passes production thresholds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.skip_ingest:
        from corpus.ingest import ingest

        ingest()
    init_db()
    routes = _split_routes(args.routes)
    limit = args.limit
    if limit is None:
        limit = get_settings().eval_fast_gate_size if args.gate == "fast" else 10_000
    with SessionLocal() as db:
        leaderboard = evaluate_models(
            db,
            limit=limit,
            determinism_runs=args.determinism_runs,
            persist=not args.no_persist,
            routes=routes,
        )
        if args.json_output:
            print(json.dumps(leaderboard, indent=2, sort_keys=True))
        else:
            _print_table(leaderboard)
        if args.print_approved_env:
            approved = approved_model_routes(db)
            print(f"APPROVED_MODELS={','.join(approved)}")
        if args.fail_on_no_production_ready and not any(
            row["production_ready"] for row in leaderboard["models"]
        ):
            return 2
    return 0


def _split_routes(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _print_table(leaderboard: dict[str, Any]) -> None:
    print(
        f"Dataset {leaderboard['dataset_version']}: "
        f"{leaderboard['evaluated_questions']}/{leaderboard['dataset_size']} cases"
    )
    header = (
        f"{'route':42} {'status':14} {'score':>7} {'outcome':>8} "
        f"{'cites':>8} {'halluc':>8} {'latency':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in leaderboard["models"]:
        print(
            f"{row['route'][:42]:42} {row['status'][:14]:14} "
            f"{_pct(row['overall_score']):>7} {_pct(row['outcome_accuracy']):>8} "
            f"{_pct(row['citation_accuracy']):>8} {_pct(row['hallucination_rate']):>8} "
            f"{str(row['avg_latency_ms'] or '-') + 'ms':>8}"
        )
        if row.get("error"):
            print(f"  error: {row['error']}")
        for failure in row.get("failure_examples", [])[:3]:
            reasons = "; ".join(failure.get("failure_reasons", [])[:2])
            print(f"  fail {failure['case_id']}: {reasons}")


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
