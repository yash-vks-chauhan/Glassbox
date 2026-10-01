"""threads + conversation context on decisions.

Adds the threads table and three nullable decision columns: thread_id,
retrieval_question (the context-resolved question a follow-up was answered
with), and refusal_reason (the refusal text shown). They join the audit hash
only when set, so existing rows keep their hashes.

Revision ID: 0011_threads
Revises: 0010_decision_reviews
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

from app.core.migration_utils import (
    add_columns_if_missing,
    create_index_if_missing,
    has_column,
    has_table,
)


revision = "0011_threads"
down_revision = "0010_decision_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("threads"):
        op.create_table(
            "threads",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("client_id", sa.String(length=64), nullable=False),
            sa.Column(
                "created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_threads_tenant_id", "threads", ["tenant_id"])
    create_index_if_missing("ix_threads_client_id", "threads", ["client_id"])

    add_columns_if_missing(
        "decisions",
        [
            sa.Column("retrieval_question", sa.Text(), nullable=True),
            sa.Column("refusal_reason", sa.Text(), nullable=True),
        ],
    )
    if not has_column("decisions", "thread_id"):
        with op.batch_alter_table("decisions") as batch:
            batch.add_column(sa.Column("thread_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key("fk_decisions_thread_id", "threads", ["thread_id"], ["id"])
    create_index_if_missing("ix_decisions_thread_id", "decisions", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_decisions_thread_id", table_name="decisions")
    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint("fk_decisions_thread_id", type_="foreignkey")
        batch.drop_column("thread_id")
        batch.drop_column("refusal_reason")
        batch.drop_column("retrieval_question")
    op.drop_index("ix_threads_client_id", table_name="threads")
    op.drop_index("ix_threads_tenant_id", table_name="threads")
    op.drop_table("threads")
