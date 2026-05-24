"""persist model evaluation gate metrics

Revision ID: 0004_model_eval_metadata
Revises: 0003_retrieved_chunks_metadata
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_model_eval_metadata"
down_revision = "0003_retrieved_chunks_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_eval_runs") as batch:
        batch.add_column(sa.Column("p50_latency_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("p95_latency_ms", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "answerability_accuracy",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column(
                "refusal_correctness",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column(
                "numeric_compliance_accuracy",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column(
                "prompt_injection_resistance",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column(
                "failure_buckets_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column("eval_gate", sa.String(length=16), nullable=False, server_default="fast")
        )

    with op.batch_alter_table("model_eval_results") as batch:
        batch.add_column(
            sa.Column("answerability_score", sa.Float(), nullable=False, server_default="0.0")
        )
        batch.add_column(
            sa.Column("refusal_score", sa.Float(), nullable=False, server_default="0.0")
        )
        batch.add_column(
            sa.Column(
                "numeric_compliance_score",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column(
                "prompt_injection_score",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )
        batch.add_column(
            sa.Column("banned_terms_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("failure_bucket", sa.String(length=64), nullable=False, server_default="other")
        )
        batch.add_column(sa.Column("gold_answer", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("adversarial", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    with op.batch_alter_table("model_eval_results") as batch:
        batch.drop_column("adversarial")
        batch.drop_column("reason")
        batch.drop_column("gold_answer")
        batch.drop_column("failure_bucket")
        batch.drop_column("banned_terms_json")
        batch.drop_column("prompt_injection_score")
        batch.drop_column("numeric_compliance_score")
        batch.drop_column("refusal_score")
        batch.drop_column("answerability_score")

    with op.batch_alter_table("model_eval_runs") as batch:
        batch.drop_column("eval_gate")
        batch.drop_column("failure_buckets_json")
        batch.drop_column("prompt_injection_resistance")
        batch.drop_column("numeric_compliance_accuracy")
        batch.drop_column("refusal_correctness")
        batch.drop_column("answerability_accuracy")
        batch.drop_column("p95_latency_ms")
        batch.drop_column("p50_latency_ms")
