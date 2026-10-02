"""Postgres DELETE / TRUNCATE guards on the tamper-evident audit tables.

0005 installs the SQLite version (``RAISE(ABORT)`` triggers). Postgres needs a
trigger function plus row-level BEFORE DELETE triggers, and a statement-level
BEFORE TRUNCATE trigger because row triggers never fire for TRUNCATE.
Corrections go to ``decision_corrections`` instead.

Revision ID: 0007_postgres_audit_guards
Revises: 0006_advisor_quality_and_escalations
Create Date: 2026-10-02
"""

from alembic import op

from app.core.audit_guards import install_postgres_audit_guards, remove_postgres_audit_guards
from app.core.migration_utils import dialect_name


revision = "0007_postgres_audit_guards"
down_revision = "0006_advisor_quality_and_escalations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if dialect_name() == "postgresql":
        install_postgres_audit_guards(op.get_bind())


def downgrade() -> None:
    if dialect_name() == "postgresql":
        remove_postgres_audit_guards(op.get_bind())
