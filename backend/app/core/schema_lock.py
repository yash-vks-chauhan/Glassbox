"""One lock for "the schema is being changed".

``alembic upgrade`` and the boot-time ``init_db`` both hold it, so servers
(or workers, or a CLI script) starting at the same time migrate and
initialise one after another instead of racing on the same DDL: two
upgrades would both run the same migration, concurrent ``CREATE OR REPLACE
FUNCTION`` fails with "tuple concurrently updated", and two SQLite boots
trip over each other's ``CREATE TRIGGER``.

- Postgres: a session-level advisory lock, shared by every app server.
- SQLite: an exclusive lock on ``<database>.schema-lock`` next to the
  database file, shared by every process using it (plus a thread lock
  within this process).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

try:
    import fcntl
except ImportError:  # Windows: threads in one process are still serialised
    fcntl = None


# Any fixed bigint works; this one is "glassbox" in ASCII.
SCHEMA_LOCK_KEY = 0x676C617373626F78

_thread_lock = threading.Lock()


@contextmanager
def schema_lock(connection: Connection) -> Iterator[None]:
    """Hold the schema lock for the database ``connection`` points at until
    the block exits."""
    if connection.dialect.name == "postgresql":
        with _postgres_lock(connection):
            yield
    elif connection.dialect.name == "sqlite":
        with _sqlite_lock(connection.engine.url.database):
            yield
    else:
        yield


@contextmanager
def _postgres_lock(connection: Connection) -> Iterator[None]:
    # Session-level, so it survives the commits made inside the block.
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": SCHEMA_LOCK_KEY})
    connection.commit()  # don't sit idle in a transaction while waiting on DDL
    try:
        yield
    finally:
        if connection.in_transaction():
            connection.rollback()
        # Explicit: a pooled connection would otherwise keep the lock.
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEMA_LOCK_KEY})
        connection.commit()


@contextmanager
def _sqlite_lock(database: str | None) -> Iterator[None]:
    with _thread_lock:
        if fcntl is None or not database or database == ":memory:":
            yield
            return
        lock_path = Path(database).with_name(Path(database).name + ".schema-lock")
        with open(lock_path, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
