"""Idempotent schema helpers for Alembic migrations.

Local SQLite databases created before the migration chain was complete got
most of their schema from ``Base.metadata.create_all`` plus the column sync in
``app.db``. Wrapping each migration step in these checks lets
``alembic upgrade head`` run cleanly against a fresh database (the production
Postgres path) *and* against those older local databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def dialect_name() -> str:
    return op.get_bind().dialect.name


def has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return column in {item["name"] for item in _inspector().get_columns(table)}


def has_index(table: str, index: str) -> bool:
    if not has_table(table):
        return False
    return index in {item["name"] for item in _inspector().get_indexes(table)}


def has_unique_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return name in {item["name"] for item in _inspector().get_unique_constraints(table)}


def missing_columns(table: str, columns: list[sa.Column]) -> list[sa.Column]:
    """Return the subset of ``columns`` that ``table`` does not have yet."""
    return [column for column in columns if not has_column(table, column.name)]


def add_columns_if_missing(table: str, columns: list[sa.Column]) -> None:
    """Add every column in ``columns`` that ``table`` lacks, in one batch."""
    pending = missing_columns(table, columns)
    if not pending:
        return
    with op.batch_alter_table(table) as batch:
        for column in pending:
            batch.add_column(column)


def create_index_if_missing(
    index: str, table: str, columns: list[str], **kwargs: object
) -> None:
    if not has_index(table, index):
        op.create_index(index, table, columns, **kwargs)
