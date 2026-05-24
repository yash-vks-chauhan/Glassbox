"""add retrieved_chunks metadata columns

The RetrievedChunk ORM model gained `file`, `chunk_index`, `source_version`,
and `selected_reason` (nullable) after the Phase A migration. Bring the
schema in sync so the orchestrator and audit endpoints can read/write them.

Revision ID: 0003_retrieved_chunks_metadata
Revises: 0002_add_tenancy_and_auth
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_retrieved_chunks_metadata"
down_revision = "0002_add_tenancy_and_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("retrieved_chunks") as batch:
        batch.add_column(sa.Column("file", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("chunk_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_version", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("selected_reason", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("retrieved_chunks") as batch:
        batch.drop_column("selected_reason")
        batch.drop_column("source_version")
        batch.drop_column("chunk_index")
        batch.drop_column("file")
