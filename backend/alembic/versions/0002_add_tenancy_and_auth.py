"""add tenancy + auth scaffolding

Phase A of docs/SECURITY-IMPLEMENTATION.md.

- Creates identity tables (tenants, users, invitations, refresh_tokens,
  password_resets, byo_keys, security_events).
- Creates the tenant-owned `clients` table (replaces frontend localStorage).
- Adds tenant_id (and user_id where relevant) to pre-existing audit and
  model-eval tables.
- Seeds a `demo` tenant and backfills every legacy row under it so the
  NOT NULL flip is safe.

Revision ID: 0002_add_tenancy_and_auth
Revises: 0001_create_audit_tables
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_tenancy_and_auth"
down_revision = "0001_create_audit_tables"
branch_labels = None
depends_on = None


DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Identity tables
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(length=24), nullable=False, server_default="standard"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="advisor"),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("mfa_secret", sa.String(length=255), nullable=True),
        sa.Column("mfa_enrolled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "user_invitations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="advisor"),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("invited_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_invitations_tenant_id", "user_invitations", ["tenant_id"])
    op.create_index("ix_user_invitations_email", "user_invitations", ["email"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])

    op.create_table(
        "byo_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_kid", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_byo_keys_user_id", "byo_keys", ["user_id"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_events_tenant_id", "security_events", ["tenant_id"])
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])

    # ------------------------------------------------------------------
    # 2. clients (tenant-owned business data)
    # ------------------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("client_code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("household", sa.String(length=255), nullable=True),
        sa.Column("risk_profile", sa.String(length=24), nullable=False),
        sa.Column("jurisdictions", sa.JSON(), nullable=False),
        sa.Column("max_single_position_pct", sa.Float(), nullable=True),
        sa.Column("min_liquid_within_30d_pct", sa.Float(), nullable=True),
        sa.Column("excluded_sectors", sa.JSON(), nullable=False),
        sa.Column("excluded_regions", sa.JSON(), nullable=False),
        sa.Column("ips_version", sa.String(length=32), nullable=True),
        sa.Column("ips_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aum_eur", sa.Float(), nullable=True),
        sa.Column("advisor_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "client_code", name="uq_clients_tenant_code"),
    )
    op.create_index("ix_clients_tenant_id", "clients", ["tenant_id"])

    # ------------------------------------------------------------------
    # 3. Seed the demo tenant + clients (so the backfill below has a target
    #    and so the tenant is immediately usable end-to-end).
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, slug, status, plan, created_at)
            VALUES (:id, :name, :slug, 'active', 'standard', CURRENT_TIMESTAMP)
            """
        ).bindparams(id=DEMO_TENANT_ID, name="Demo Tenant", slug="demo")
    )
    _seed_demo_clients()

    # ------------------------------------------------------------------
    # 4. Extend legacy tables in ONE batch per table.
    #    On SQLite, batch_alter_table rebuilds the table; doing multiple
    #    batches for one table is fragile, so do everything per-table here.
    #    For the NOT NULL flip we need the backfill UPDATE to land first,
    #    so the column is added in this batch as nullable, then the UPDATE
    #    runs, then a follow-up batch enforces NOT NULL.
    # ------------------------------------------------------------------

    # 4a. Add nullable columns first.
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))

    with op.batch_alter_table("decision_claims") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))

    with op.batch_alter_table("retrieved_chunks") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))

    with op.batch_alter_table("model_eval_runs") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))

    with op.batch_alter_table("model_eval_results") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))

    # 4b. Backfill every existing row under the demo tenant.
    op.execute(sa.text("UPDATE decisions SET tenant_id = :t").bindparams(t=DEMO_TENANT_ID))
    op.execute(sa.text("UPDATE decision_claims SET tenant_id = :t").bindparams(t=DEMO_TENANT_ID))
    op.execute(sa.text("UPDATE retrieved_chunks SET tenant_id = :t").bindparams(t=DEMO_TENANT_ID))
    # model_eval_* stay NULL on purpose — those are platform-wide rows.

    # 4c. Recreate the tables with NOT NULL + FK + indexes for the three
    #     tenant-owned audit tables. (Model-eval tables keep tenant_id nullable.)
    with op.batch_alter_table("decisions") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_foreign_key("fk_decisions_tenant_id", "tenants", ["tenant_id"], ["id"])
        batch.create_foreign_key("fk_decisions_user_id", "users", ["user_id"], ["id"])
        batch.create_index("ix_decisions_tenant_id", ["tenant_id"])
        batch.create_index("ix_decisions_user_id", ["user_id"])
        batch.create_index("ix_decisions_created_at", ["created_at"])

    with op.batch_alter_table("decision_claims") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_foreign_key("fk_decision_claims_tenant_id", "tenants", ["tenant_id"], ["id"])
        batch.create_index("ix_decision_claims_tenant_id", ["tenant_id"])

    with op.batch_alter_table("retrieved_chunks") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_foreign_key("fk_retrieved_chunks_tenant_id", "tenants", ["tenant_id"], ["id"])
        batch.create_index("ix_retrieved_chunks_tenant_id", ["tenant_id"])

    with op.batch_alter_table("model_eval_runs") as batch:
        batch.create_foreign_key("fk_model_eval_runs_tenant_id", "tenants", ["tenant_id"], ["id"])
        batch.create_index("ix_model_eval_runs_tenant_id", ["tenant_id"])

    with op.batch_alter_table("model_eval_results") as batch:
        batch.create_foreign_key("fk_model_eval_results_tenant_id", "tenants", ["tenant_id"], ["id"])
        batch.create_index("ix_model_eval_results_tenant_id", ["tenant_id"])


def _seed_demo_clients() -> None:
    """Seed the four demo clients (mirrors frontend/lib/clients.ts SEED_CLIENTS)
    so the demo tenant is usable end-to-end the moment the migration finishes."""
    rows = [
        {
            "id": "11111111-1111-1111-1111-000000000001",
            "code": "C001",
            "name": "Müller Family Office",
            "household": "DACH · Zurich",
            "risk_profile": "moderate",
            "jurisdictions": '["CH","US"]',
            "max_pos": 25.0,
            "min_liq": 15.0,
            "excl_sectors": '["tobacco","firearms"]',
            "excl_regions": '["russia"]',
            "ips_version": "v3.2",
            "ips_updated_at": "2024-11-18",
            "aum": 18_400_000,
            "advisor": "S. Kühn",
        },
        {
            "id": "11111111-1111-1111-1111-000000000002",
            "code": "C002",
            "name": "Vance Conservative Trust",
            "household": "US · Boston",
            "risk_profile": "conservative",
            "jurisdictions": '["US"]',
            "max_pos": 15.0,
            "min_liq": 30.0,
            "excl_sectors": '["tobacco","firearms","gambling","cryptocurrency"]',
            "excl_regions": '["russia","sanctioned_markets"]',
            "ips_version": "v2.7",
            "ips_updated_at": "2025-01-09",
            "aum": 6_900_000,
            "advisor": "A. Lopez",
        },
        {
            "id": "11111111-1111-1111-1111-000000000003",
            "code": "C003",
            "name": "Tan Growth Mandate",
            "household": "APAC · Singapore",
            "risk_profile": "aggressive",
            "jurisdictions": '["CH","SG"]',
            "max_pos": 35.0,
            "min_liq": 10.0,
            "excl_sectors": '["tobacco"]',
            "excl_regions": '["russia"]',
            "ips_version": "v4.0",
            "ips_updated_at": "2025-03-02",
            "aum": 42_000_000,
            "advisor": "M. Reis",
        },
        {
            "id": "11111111-1111-1111-1111-000000000004",
            "code": "C004",
            "name": "Chauhan Growth Mandate",
            "household": "IN · Mumbai",
            "risk_profile": "moderate",
            "jurisdictions": '["IN","SG"]',
            "max_pos": 20.0,
            "min_liq": 12.0,
            "excl_sectors": '["cryptocurrency","gambling"]',
            "excl_regions": '["russia"]',
            "ips_version": "v1.1",
            "ips_updated_at": "2026-05-22",
            "aum": 12_800_000,
            "advisor": "R. Mehta",
        },
    ]
    insert_sql = sa.text(
        """
        INSERT INTO clients (
            id, tenant_id, client_code, display_name, household, risk_profile,
            jurisdictions, max_single_position_pct, min_liquid_within_30d_pct,
            excluded_sectors, excluded_regions, ips_version, ips_updated_at,
            aum_eur, advisor_name, created_at
        ) VALUES (
            :id, :tenant_id, :code, :name, :household, :risk_profile,
            :jurisdictions, :max_pos, :min_liq,
            :excl_sectors, :excl_regions, :ips_version, :ips_updated_at,
            :aum, :advisor, CURRENT_TIMESTAMP
        )
        """
    )
    for r in rows:
        op.execute(insert_sql.bindparams(tenant_id=DEMO_TENANT_ID, **r))


def downgrade() -> None:
    # Reverse the schema changes. Data on legacy tables is preserved (we only
    # drop the columns we added).
    with op.batch_alter_table("model_eval_results") as batch:
        batch.drop_index("ix_model_eval_results_tenant_id")
        batch.drop_constraint("fk_model_eval_results_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")

    with op.batch_alter_table("model_eval_runs") as batch:
        batch.drop_index("ix_model_eval_runs_tenant_id")
        batch.drop_constraint("fk_model_eval_runs_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")

    with op.batch_alter_table("retrieved_chunks") as batch:
        batch.drop_index("ix_retrieved_chunks_tenant_id")
        batch.drop_constraint("fk_retrieved_chunks_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")

    with op.batch_alter_table("decision_claims") as batch:
        batch.drop_index("ix_decision_claims_tenant_id")
        batch.drop_constraint("fk_decision_claims_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")

    with op.batch_alter_table("decisions") as batch:
        batch.drop_index("ix_decisions_created_at")
        batch.drop_index("ix_decisions_user_id")
        batch.drop_index("ix_decisions_tenant_id")
        batch.drop_constraint("fk_decisions_user_id", type_="foreignkey")
        batch.drop_constraint("fk_decisions_tenant_id", type_="foreignkey")
        batch.drop_column("user_id")
        batch.drop_column("tenant_id")

    op.drop_index("ix_clients_tenant_id", table_name="clients")
    op.drop_table("clients")

    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    op.drop_index("ix_security_events_tenant_id", table_name="security_events")
    op.drop_table("security_events")

    op.drop_index("ix_byo_keys_user_id", table_name="byo_keys")
    op.drop_table("byo_keys")

    op.drop_index("ix_password_resets_user_id", table_name="password_resets")
    op.drop_table("password_resets")

    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_user_invitations_email", table_name="user_invitations")
    op.drop_index("ix_user_invitations_tenant_id", table_name="user_invitations")
    op.drop_table("user_invitations")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_table("tenants")
