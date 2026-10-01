"""Widen users.mfa_secret to TEXT.

The column holds the (now encrypted) TOTP secret together with ten recovery
code hashes, which is far longer than VARCHAR(255). SQLite never enforced the
limit; Postgres does, so MFA enrolment failed there.

Revision ID: 0008_mfa_secret_text
Revises: 0007_postgres_audit_guards
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_mfa_secret_text"
down_revision = "0007_postgres_audit_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "mfa_secret",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "mfa_secret",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
