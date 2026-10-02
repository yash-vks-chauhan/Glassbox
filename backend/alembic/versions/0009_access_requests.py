"""access_requests: submissions from the public contact page.

Revision ID: 0009_access_requests
Revises: 0008_mfa_secret_text
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

from app.core.migration_utils import create_index_if_missing, has_table


revision = "0009_access_requests"
down_revision = "0008_mfa_secret_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("access_requests"):
        op.create_table(
            "access_requests",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("company", sa.String(length=160), nullable=False),
            sa.Column("work_email", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=120), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
        )
    create_index_if_missing("ix_access_requests_created_at", "access_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_requests_created_at", table_name="access_requests")
    op.drop_table("access_requests")
