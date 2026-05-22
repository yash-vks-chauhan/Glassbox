"""create audit tables

Revision ID: 0001_create_audit_tables
Revises:
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_create_audit_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("retrieved_chunks")
    op.drop_table("decision_claims")
    op.drop_table("decisions")
