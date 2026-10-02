"""Migration chain and boot checks.

A Postgres deployment gets its schema only from ``alembic upgrade head``, so
these tests drive the real chain against throwaway databases:

- a fresh database migrates to head and matches the ORM models (SQLite, and
  Postgres when the suite runs there);
- pre-tenancy rows are backfilled into the demo tenant by 0002;
- a database built by ``create_all()`` (how local dev databases were made)
  and stamped at an older revision still upgrades cleanly;
- servers starting together don't race: concurrent upgrades and concurrent
  ``init_db`` calls take turns under the schema lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, make_url, text

from app.db import init_db
from app.models_db import Base, DEMO_TENANT_ID


BACKEND_DIR = Path(__file__).resolve().parents[1]
POSTGRES_TEST_URL = os.environ.get("GLASSBOX_TEST_DATABASE_URL", "").strip()
needs_postgres = pytest.mark.skipif(
    not POSTGRES_TEST_URL, reason="needs GLASSBOX_TEST_DATABASE_URL (Postgres)"
)


def _config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = url
    return config


def _schema_diff(url: str) -> list:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migrations.db'}"


@pytest.fixture()
def scratch_postgres_url():
    """A fresh, empty database on the Postgres server the suite runs on."""
    base = make_url(POSTGRES_TEST_URL)
    name = f"{base.database}_scratch_{uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_fresh_database_upgrades_to_head_and_matches_models(db_url: str) -> None:
    command.upgrade(_config(db_url), "head")
    assert _schema_diff(db_url) == []


def test_pre_tenancy_rows_are_backfilled_into_demo_tenant(db_url: str) -> None:
    config = _config(db_url)
    command.upgrade(config, "0001_create_audit_tables")
    decision_id = str(uuid4())
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO decisions (id, created_at, question, outcome, llm_model, latency_ms) "
                    "VALUES (:id, CURRENT_TIMESTAMP, 'legacy question', 'answered', 'legacy', 5)"
                ),
                {"id": decision_id},
            )
            conn.execute(
                text(
                    "INSERT INTO decision_claims (id, decision_id, claim_text, verified, kept) "
                    "VALUES (:id, :decision_id, 'legacy claim', 1, 1)"
                ),
                {"id": str(uuid4()), "decision_id": decision_id},
            )

        command.upgrade(config, "head")

        with engine.connect() as conn:
            decision_tenant = conn.execute(
                text("SELECT tenant_id FROM decisions WHERE id = :id"), {"id": decision_id}
            ).scalar_one()
            claim_tenants = conn.execute(
                text("SELECT DISTINCT tenant_id FROM decision_claims")
            ).scalars().all()
    finally:
        engine.dispose()
    assert decision_tenant == DEMO_TENANT_ID
    assert claim_tenants == [DEMO_TENANT_ID]


def test_create_all_database_stamped_at_older_revision_upgrades(db_url: str) -> None:
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    config = _config(db_url)
    command.stamp(config, "0003_retrieved_chunks_metadata")
    command.upgrade(config, "head")
    assert _schema_diff(db_url) == []


@needs_postgres
def test_fresh_postgres_database_upgrades_to_head_and_matches_models(scratch_postgres_url):
    command.upgrade(_config(scratch_postgres_url), "head")
    assert _schema_diff(scratch_postgres_url) == []


@needs_postgres
def test_concurrent_upgrades_take_turns(scratch_postgres_url):
    """Replicas that run `alembic upgrade head` as they start, at the same
    moment, must all succeed: the first migrates, the rest find head."""
    script = (
        "import sys; from alembic import command; from alembic.config import Config; "
        "config = Config('alembic.ini'); config.attributes['database_url'] = sys.argv[1]; "
        "command.upgrade(config, 'head')"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, scratch_postgres_url],
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    failures = []
    for process in processes:
        _, stderr = process.communicate(timeout=180)
        if process.returncode != 0:
            failures.append(stderr[-2000:])
    assert failures == []
    assert _schema_diff(scratch_postgres_url) == []


def test_concurrent_boots_take_turns():
    """Workers running init_db at once (uvicorn --workers, or replicas
    starting together) must all come up."""
    workers = 4
    start = threading.Barrier(workers)
    errors: list[BaseException] = []

    def boot() -> None:
        try:
            start.wait()
            init_db()
        except BaseException as exc:  # noqa: BLE001 — re-raised in the test thread
            errors.append(exc)

    threads = [threading.Thread(target=boot) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
