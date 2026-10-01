"""Database-level guards that make the audit tables append-only.

``decisions``, ``decision_claims`` and ``retrieved_chunks`` form the
tamper-evident hash chain, so the database itself refuses to delete their
rows. Corrections are recorded in ``decision_corrections`` instead.

Both supported dialects get equivalent guards:

- SQLite: ``BEFORE DELETE`` triggers that ``RAISE(ABORT)``.
- Postgres: a trigger function wired to row-level ``BEFORE DELETE`` triggers
  and statement-level ``BEFORE TRUNCATE`` triggers.

Every function here is idempotent, so it is safe to call on each boot.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


AUDIT_TABLES = ("decisions", "decision_claims", "retrieved_chunks")
GUARD_MESSAGE = "audit row deletion blocked — use decision_corrections instead"
_PG_FUNCTION = "glassbox_block_audit_delete"


def delete_trigger_name(table: str) -> str:
    return f"trg_no_delete_{table}"


def truncate_trigger_name(table: str) -> str:
    return f"trg_no_truncate_{table}"


def install_audit_guards(conn: Connection) -> None:
    """Install the guards for whichever dialect ``conn`` is using."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        install_sqlite_audit_guards(conn)
    elif dialect == "postgresql":
        install_postgres_audit_guards(conn)


def remove_audit_guards(conn: Connection) -> None:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        remove_sqlite_audit_guards(conn)
    elif dialect == "postgresql":
        remove_postgres_audit_guards(conn)


def _existing_audit_tables(conn: Connection) -> list[str]:
    tables = set(inspect(conn).get_table_names())
    return [table for table in AUDIT_TABLES if table in tables]


def install_sqlite_audit_guards(conn: Connection) -> None:
    for table in _existing_audit_tables(conn):
        trigger = delete_trigger_name(table)
        # Drop + recreate so the trigger always reflects the current message.
        conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        conn.execute(
            text(
                f"CREATE TRIGGER {trigger} BEFORE DELETE ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{GUARD_MESSAGE}'); END"
            )
        )


def remove_sqlite_audit_guards(conn: Connection) -> None:
    for table in AUDIT_TABLES:
        conn.execute(text(f"DROP TRIGGER IF EXISTS {delete_trigger_name(table)}"))


def install_postgres_audit_guards(conn: Connection) -> None:
    conn.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION {_PG_FUNCTION}() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{GUARD_MESSAGE}';
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    for table in _existing_audit_tables(conn):
        delete_trigger = delete_trigger_name(table)
        truncate_trigger = truncate_trigger_name(table)
        conn.execute(text(f"DROP TRIGGER IF EXISTS {delete_trigger} ON {table}"))
        conn.execute(
            text(
                f"CREATE TRIGGER {delete_trigger} BEFORE DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {_PG_FUNCTION}()"
            )
        )
        conn.execute(text(f"DROP TRIGGER IF EXISTS {truncate_trigger} ON {table}"))
        conn.execute(
            text(
                f"CREATE TRIGGER {truncate_trigger} BEFORE TRUNCATE ON {table} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {_PG_FUNCTION}()"
            )
        )


def remove_postgres_audit_guards(conn: Connection) -> None:
    for table in _existing_audit_tables(conn):
        conn.execute(text(f"DROP TRIGGER IF EXISTS {delete_trigger_name(table)} ON {table}"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS {truncate_trigger_name(table)} ON {table}"))
    conn.execute(text(f"DROP FUNCTION IF EXISTS {_PG_FUNCTION}()"))
