"""create audit tables

Also creates the model-eval tables in their pre-tenancy shape. The original
build created those with ``create_all`` only, so 0002 (which adds their
``tenant_id``) failed on a fresh database.

Revision ID: 0001_create_audit_tables
Revises:
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

from app.core.migration_utils import has_table


revision = "0001_create_audit_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("decisions"):
        _create_audit_tables()
    if not has_table("model_eval_runs"):
        _create_model_eval_tables()


def _create_audit_tables() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("determinism_score", sa.Float(), nullable=True),
        sa.Column("grounding_score", sa.Float(), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_table(
        "decision_claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("cited_source_id", sa.String(length=64), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("kept", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "retrieved_chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
    )


def _create_model_eval_tables() -> None:
    # Columns added later by 0002 (tenant_id), 0004 (gate metrics), and 0006
    # (advisor quality) are deliberately absent here.
    op.create_table(
        "model_eval_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_size", sa.Integer(), nullable=False),
        sa.Column("evaluated_questions", sa.Integer(), nullable=False),
        sa.Column("thresholds_json", sa.Text(), nullable=False),
        sa.Column("category_scores_json", sa.Text(), nullable=False),
        sa.Column("production_ready", sa.Boolean(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("outcome_accuracy", sa.Float(), nullable=False),
        sa.Column("citation_accuracy", sa.Float(), nullable=False),
        sa.Column("retrieval_recall", sa.Float(), nullable=False),
        sa.Column("faithfulness_score", sa.Float(), nullable=False),
        sa.Column("golden_claim_score", sa.Float(), nullable=False),
        sa.Column("hallucination_rate", sa.Float(), nullable=False),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column("determinism", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "model_eval_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id", sa.String(length=36), sa.ForeignKey("model_eval_runs.id"), nullable=False
        ),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("expected_outcome", sa.String(length=24), nullable=False),
        sa.Column("actual_outcome", sa.String(length=24), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("outcome_score", sa.Float(), nullable=False),
        sa.Column("citation_score", sa.Float(), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("faithfulness_score", sa.Float(), nullable=False),
        sa.Column("golden_claim_score", sa.Float(), nullable=False),
        sa.Column("hallucinated", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("expected_sources_json", sa.Text(), nullable=False),
        sa.Column("cited_sources_json", sa.Text(), nullable=False),
        sa.Column("retrieved_sources_json", sa.Text(), nullable=False),
        sa.Column("missing_terms_json", sa.Text(), nullable=False),
        sa.Column("failure_reasons_json", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("model_eval_results")
    op.drop_table("model_eval_runs")
    op.drop_table("retrieved_chunks")
    op.drop_table("decision_claims")
    op.drop_table("decisions")
