"""Phase E hardening — audit hash chain, BYO key last4,
decision_corrections, rate_limit_buckets, audit DELETE guards.

Revision ID: 0005_phase_e_hardening
Revises: 0004_model_eval_metadata
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_phase_e_hardening"
down_revision = "0004_model_eval_metadata"
branch_labels = None
depends_on = None


_AUDIT_DELETE_TRIGGERS = {
    "decisions": "trg_no_delete_decisions",
    "decision_claims": "trg_no_delete_decision_claims",
    "retrieved_chunks": "trg_no_delete_retrieved_chunks",
}


def upgrade() -> None:
    # 1. Hash chain columns on decisions.
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("row_hash", sa.String(length=64), nullable=True))

    # 2. BYO key UX field.
    with op.batch_alter_table("byo_keys") as batch:
        batch.add_column(sa.Column("last4", sa.String(length=8), nullable=True))

    # 3. Append-only correction log so we never mutate audit rows.
    op.create_table(
        "decision_corrections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("corrected_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("corrected_outcome", sa.String(length=24), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_corrections_tenant_id", "decision_corrections", ["tenant_id"])
    op.create_index("ix_decision_corrections_decision_id", "decision_corrections", ["decision_id"])

    # 4. Rate-limit bucket store (sliding window keyed on (subject, route)).
    op.create_table(
        "rate_limit_buckets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("route_class", sa.String(length=32), nullable=False),
        sa.Column("hits_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject", "route_class", name="uq_rate_limit_subject_route"),
    )
    op.create_index("ix_rate_limit_buckets_subject", "rate_limit_buckets", ["subject"])

    # 5. Per-(user_id, provider) unique constraint for byo_keys.
    with op.batch_alter_table("byo_keys") as batch:
        batch.create_unique_constraint(
            "uq_byo_keys_user_provider", ["user_id", "provider"]
        )

    # 6. SQLite DELETE-guards on the audit tables. Postgres targets get
    #    equivalent triggers from a separate migration; we keep the SQL
    #    inline here because alembic doesn't have a portable RAISE primitive.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table, trigger in _AUDIT_DELETE_TRIGGERS.items():
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {trigger} BEFORE DELETE ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, 'audit row deletion blocked — "
                    f"use decision_corrections instead'); END"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for trigger in _AUDIT_DELETE_TRIGGERS.values():
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))

    with op.batch_alter_table("byo_keys") as batch:
        batch.drop_constraint("uq_byo_keys_user_provider", type_="unique")
        batch.drop_column("last4")

    op.drop_index("ix_rate_limit_buckets_subject", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")

    op.drop_index("ix_decision_corrections_decision_id", table_name="decision_corrections")
    op.drop_index("ix_decision_corrections_tenant_id", table_name="decision_corrections")
    op.drop_table("decision_corrections")

    with op.batch_alter_table("decisions") as batch:
        batch.drop_column("row_hash")
        batch.drop_column("prev_hash")
