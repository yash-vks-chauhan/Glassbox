"""advisor answer quality metrics and durable escalations

Revision ID: 0006_advisor_quality_and_escalations
Revises: 0005_phase_e_hardening
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_advisor_quality_and_escalations"
down_revision = "0005_phase_e_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_eval_runs") as batch:
        batch.add_column(
            sa.Column(
                "advisor_quality_score",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )

    with op.batch_alter_table("model_eval_results") as batch:
        batch.add_column(
            sa.Column(
                "advisor_quality_score",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )

    op.create_table(
        "escalations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_role", sa.String(length=24), nullable=False, server_default="compliance"),
        sa.Column("assigned_to_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_escalations_tenant_id", "escalations", ["tenant_id"])
    op.create_index("ix_escalations_decision_id", "escalations", ["decision_id"])
    op.create_index("ix_escalations_status", "escalations", ["status"])
    op.create_index(
        "uq_escalations_active_decision",
        "escalations",
        ["tenant_id", "decision_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('open', 'in_review')"),
    )

    op.create_table(
        "escalation_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("escalation_id", sa.String(length=36), sa.ForeignKey("escalations.id"), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_escalation_events_tenant_id", "escalation_events", ["tenant_id"])
    op.create_index("ix_escalation_events_escalation_id", "escalation_events", ["escalation_id"])


def downgrade() -> None:
    op.drop_index("ix_escalation_events_escalation_id", table_name="escalation_events")
    op.drop_index("ix_escalation_events_tenant_id", table_name="escalation_events")
    op.drop_table("escalation_events")

    op.drop_index("ix_escalations_status", table_name="escalations")
    op.drop_index("uq_escalations_active_decision", table_name="escalations")
    op.drop_index("ix_escalations_decision_id", table_name="escalations")
    op.drop_index("ix_escalations_tenant_id", table_name="escalations")
    op.drop_table("escalations")

    with op.batch_alter_table("model_eval_results") as batch:
        batch.drop_column("advisor_quality_score")

    with op.batch_alter_table("model_eval_runs") as batch:
        batch.drop_column("advisor_quality_score")
