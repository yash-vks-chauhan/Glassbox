"""determinism_schedules + determinism_runs.

The determinism harness used to persist every repeat run as an audit
decision and then edit a hashed field. Runs now live in their own table and
leave the audit log untouched.

Revision ID: 0012_determinism
Revises: 0011_threads
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

from app.core.migration_utils import create_index_if_missing, has_table


revision = "0012_determinism"
down_revision = "0011_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("determinism_schedules"):
        op.create_table(
            "determinism_schedules",
            sa.Column(
                "tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), primary_key=True
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("hour_utc", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("runs_per_question", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="10"),
            sa.Column(
                "updated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not has_table("determinism_runs"):
        op.create_table(
            "determinism_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_by", sa.String(length=16), nullable=False),
            sa.Column(
                "requested_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("scheduled_for", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("model_route", sa.String(length=255), nullable=True),
            sa.Column("runs_per_question", sa.Integer(), nullable=False),
            sa.Column("question_count", sa.Integer(), nullable=False),
            sa.Column("avg_score", sa.Float(), nullable=True),
            sa.Column("min_score", sa.Float(), nullable=True),
            sa.Column("results_json", sa.Text(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "tenant_id", "scheduled_for", name="uq_determinism_runs_schedule_day"
            ),
        )
    create_index_if_missing("ix_determinism_runs_tenant_id", "determinism_runs", ["tenant_id"])
    create_index_if_missing("ix_determinism_runs_created_at", "determinism_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_determinism_runs_created_at", table_name="determinism_runs")
    op.drop_index("ix_determinism_runs_tenant_id", table_name="determinism_runs")
    op.drop_table("determinism_runs")
    op.drop_table("determinism_schedules")
