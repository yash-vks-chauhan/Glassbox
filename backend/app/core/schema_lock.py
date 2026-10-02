"""One Postgres advisory lock for "the schema is being changed".

``alembic upgrade`` and the boot-time ``init_db`` both hold it, so app
servers that start at the same time migrate and initialise one after
another instead of racing on the same DDL (concurrent ``CREATE OR REPLACE
FUNCTION`` fails with "tuple concurrently updated", and two upgrades would
both run the same migration). SQLite is single-process, so it needs none.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Connection


# Any fixed bigint works; this one is "glassbox" in ASCII.
SCHEMA_LOCK_KEY = 0x676C617373626F78


@contextmanager
def schema_lock(connection: Connection) -> Iterator[None]:
    """Hold the lock on ``connection`` (session-level, so it survives the
    commits made inside) until the block exits."""
    if connection.dialect.name != "postgresql":
        yield
        return
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
