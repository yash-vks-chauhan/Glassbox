"""Background scheduler for the nightly determinism harness.

A daemon thread wakes every DETERMINISM_SCHEDULER_INTERVAL_SECONDS and runs
whatever schedules are due (``run_due_schedules``). Each scheduled run is
claimed per tenant per day in the database, so several server processes can
all run the scheduler without duplicating work.
"""

from __future__ import annotations

import logging
import threading

from app.core.determinism import run_due_schedules
from app.db import SessionLocal


logger = logging.getLogger(__name__)


class DeterminismScheduler:
    def __init__(self, interval_seconds: int) -> None:
        self._interval = max(30, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="determinism-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def tick(self) -> None:
        try:
            with SessionLocal() as db:
                for run in run_due_schedules(db):
                    logger.info(
                        "determinism_run_completed tenant=%s run=%s avg=%s",
                        run.tenant_id, run.id, run.avg_score,
                    )
        except Exception:  # noqa: BLE001 — keep the scheduler alive
            logger.exception("determinism_scheduler_tick_failed")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)
