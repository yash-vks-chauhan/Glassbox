"""Run the determinism harness from the command line.

Usage (from backend/):
    PYTHONPATH=. python -m scripts.run_determinism --due
        Run every tenant schedule that is due now (for cron; safe to run
        from several hosts because each day's run is claimed in the DB).
    PYTHONPATH=. python -m scripts.run_determinism --tenant <tenant-id> [--runs 5] [--sample 10]
        Run once now for one tenant.
"""

from __future__ import annotations

import argparse

from app.core.determinism import get_schedule, run_due_schedules, run_now
from app.db import SessionLocal, init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the determinism harness.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--due", action="store_true", help="run every schedule that is due")
    target.add_argument("--tenant", help="run once now for this tenant id")
    parser.add_argument("--runs", type=int, help="answers per question (2-10)")
    parser.add_argument("--sample", type=int, help="questions to sample (1-25)")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as db:
        if args.due:
            runs = run_due_schedules(db)
        else:
            schedule = get_schedule(db, args.tenant)
            runs = [
                run_now(
                    db,
                    tenant_id=args.tenant,
                    user_id=None,
                    runs_per_question=max(2, min(10, args.runs or schedule.runs_per_question)),
                    sample_size=max(1, min(25, args.sample or schedule.sample_size)),
                )
            ]
        for run in runs:
            score = "n/a" if run.avg_score is None else f"{run.avg_score:.3f}"
            print(
                f"tenant {run.tenant_id}: {run.status}, {run.question_count} questions, "
                f"avg determinism {score}"
            )
        if not runs:
            print("No schedules were due.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
