"""decision_reviews + claim_labels: reviewer verdicts and labelled claims.

Revision ID: 0010_decision_reviews
Revises: 0009_access_requests
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

from app.core.migration_utils import create_index_if_missing, has_table


revision = "0010_decision_reviews"
down_revision = "0009_access_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("decision_reviews"):
        op.create_table(
            "decision_reviews",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False
            ),
            sa.Column(
                "escalation_id", sa.String(length=36), sa.ForeignKey("escalations.id"), nullable=True
            ),
            sa.Column(
                "reviewer_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("assessment", sa.String(length=32), nullable=False),
            sa.Column("reason_code", sa.String(length=64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("corrected_outcome", sa.String(length=24), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_decision_reviews_tenant_id", "decision_reviews", ["tenant_id"])
    create_index_if_missing("ix_decision_reviews_decision_id", "decision_reviews", ["decision_id"])

    if not has_table("claim_labels"):
        op.create_table(
            "claim_labels",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "review_id", sa.String(length=36), sa.ForeignKey("decision_reviews.id"), nullable=False
            ),
            sa.Column(
                "decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False
            ),
            sa.Column(
                "claim_id", sa.String(length=36), sa.ForeignKey("decision_claims.id"), nullable=False
            ),
            sa.Column("claim_text", sa.Text(), nullable=False),
            sa.Column("cited_source_id", sa.String(length=64), nullable=True),
            sa.Column("source_text", sa.Text(), nullable=True),
            sa.Column("supported", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    create_index_if_missing("ix_claim_labels_tenant_id", "claim_labels", ["tenant_id"])
    create_index_if_missing("ix_claim_labels_review_id", "claim_labels", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_claim_labels_review_id", table_name="claim_labels")
    op.drop_index("ix_claim_labels_tenant_id", table_name="claim_labels")
    op.drop_table("claim_labels")
    op.drop_index("ix_decision_reviews_decision_id", table_name="decision_reviews")
    op.drop_index("ix_decision_reviews_tenant_id", table_name="decision_reviews")
    op.drop_table("decision_reviews")
