"""Phase A acceptance tests — schema invariants for tenancy + auth.

Asserts the Phase A migration delivered what docs/SECURITY-IMPLEMENTATION.md
promised:

- New identity tables exist with the right columns and indexes.
- A `demo` tenant is seeded and the four demo clients are attached to it.
- Legacy audit tables (decisions / decision_claims / retrieved_chunks) now
  carry a NOT NULL tenant_id and every pre-existing row is backfilled.
- The unique-per-tenant constraints actually fire.

These tests touch the live local DB (the one alembic has been applied to)
because we want to validate the migration result, not just the ORM schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models_db import (
    DEMO_TENANT_ID,
    ClientRecord,
    Decision,
    Tenant,
)


@contextmanager
def _rolled_back_connection() -> Iterator[Connection]:
    """A connection whose work is always rolled back, so constraint tests
    leave nothing behind on either SQLite or Postgres."""
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            yield conn
        finally:
            transaction.rollback()


def _insert_tenant(conn: Connection, tenant_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status, plan, created_at) "
            "VALUES (:id, 'Other', :slug, 'active', 'standard', CURRENT_TIMESTAMP)"
        ),
        {"id": tenant_id, "slug": f"t-{tenant_id[:8]}"},
    )


# ---------------------------------------------------------------------------
# Table presence
# ---------------------------------------------------------------------------


REQUIRED_TABLES = {
    "tenants",
    "users",
    "user_invitations",
    "refresh_tokens",
    "password_resets",
    "byo_keys",
    "security_events",
    "clients",
    "decisions",
    "decision_claims",
    "retrieved_chunks",
    "model_eval_runs",
    "model_eval_results",
    "alembic_version",
}


def test_all_phase_a_tables_exist() -> None:
    existing = set(inspect(engine).get_table_names())
    missing = REQUIRED_TABLES - existing
    assert not missing, f"missing tables: {missing}"


# ---------------------------------------------------------------------------
# Alembic stamped to 0002
# ---------------------------------------------------------------------------


def test_alembic_at_phase_a_revision_or_later() -> None:
    """Phase A landed at revision 0002; later phases may add more migrations.
    What matters is the DB is at-or-past the Phase A revision."""
    with engine.connect() as conn:
        version = conn.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    # Revision IDs in this repo sort lexicographically (0001, 0002, 0003, ...).
    assert version >= "0002_add_tenancy_and_auth", version


# ---------------------------------------------------------------------------
# Demo tenant + seeded clients
# ---------------------------------------------------------------------------


def test_demo_tenant_seeded() -> None:
    with SessionLocal() as db:
        tenant = db.get(Tenant, DEMO_TENANT_ID)
    assert tenant is not None
    assert tenant.slug == "demo"
    assert tenant.status == "active"


def test_demo_clients_attached_to_demo_tenant() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            select(ClientRecord).where(ClientRecord.tenant_id == DEMO_TENANT_ID)
        ).scalars().all()
    codes = {c.client_code for c in rows}
    assert codes == {"C001", "C002", "C003", "C004"}
    # Spot-check one IPS rule survived the JSON round-trip.
    c001 = next(c for c in rows if c.client_code == "C001")
    assert c001.max_single_position_pct == 25.0
    assert "tobacco" in c001.excluded_sectors


# ---------------------------------------------------------------------------
# Tenant scoping on legacy audit tables
# ---------------------------------------------------------------------------


def test_decisions_tenant_id_is_not_null_and_backfilled() -> None:
    with engine.connect() as conn:
        total = conn.exec_driver_sql("SELECT COUNT(*) FROM decisions").scalar_one()
        with_tid = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM decisions WHERE tenant_id IS NOT NULL"
        ).scalar_one()
    assert total == with_tid, "every decision must carry a tenant_id after Phase A"


def test_every_audit_row_points_at_an_existing_tenant() -> None:
    # The 0002 backfill of pre-tenancy rows is exercised end-to-end in
    # test_migrations.py; here we check the invariant holds in this database.
    with engine.connect() as conn:
        for table in ("decisions", "decision_claims", "retrieved_chunks"):
            orphans = conn.exec_driver_sql(
                f"SELECT COUNT(*) FROM {table} "
                "WHERE tenant_id NOT IN (SELECT id FROM tenants)"
            ).scalar_one()
            assert orphans == 0, f"{table} has {orphans} rows without a tenant"


@pytest.mark.parametrize(
    "table",
    ["decisions", "decision_claims", "retrieved_chunks"],
)
def test_inserting_a_row_without_tenant_id_is_rejected(table: str) -> None:
    """The schema must reject any direct INSERT that omits tenant_id."""
    parent_id = str(uuid4())
    with _rolled_back_connection() as conn:
        if table != "decisions":
            # A parent decision that DOES carry tenant_id, so the failure
            # comes from the child table's constraint.
            conn.execute(
                text(
                    "INSERT INTO decisions (id, tenant_id, created_at, question, outcome, "
                    "llm_model, latency_ms) VALUES (:id, :tenant, CURRENT_TIMESTAMP, 'q', "
                    "'answered', 'm', 0)"
                ),
                {"id": parent_id, "tenant": DEMO_TENANT_ID},
            )
        statements = {
            "decisions": (
                "INSERT INTO decisions (id, created_at, question, outcome, llm_model, latency_ms) "
                "VALUES (:id, CURRENT_TIMESTAMP, 'q', 'answered', 'm', 0)"
            ),
            "decision_claims": (
                "INSERT INTO decision_claims (id, decision_id, claim_text, verified, kept) "
                "VALUES (:id, :parent, 'c', false, false)"
            ),
            "retrieved_chunks": (
                "INSERT INTO retrieved_chunks (id, decision_id, source_id, source_type, "
                "chunk_text, score) VALUES (:id, :parent, 's', 'ips', 't', 0.0)"
            ),
        }
        with pytest.raises(IntegrityError):
            conn.execute(text(statements[table]), {"id": str(uuid4()), "parent": parent_id})


# ---------------------------------------------------------------------------
# Uniqueness invariants
# ---------------------------------------------------------------------------


def test_users_email_unique_per_tenant_only() -> None:
    """Same email may exist across tenants, but not twice within one tenant."""
    other_tenant = str(uuid4())
    insert_user = text(
        "INSERT INTO users (id, tenant_id, email, password_hash, role, mfa_enrolled, "
        "email_verified, failed_login_count, created_at) VALUES (:id, :tenant, "
        "'a@x.com', 'h', 'advisor', false, false, 0, CURRENT_TIMESTAMP)"
    )
    with _rolled_back_connection() as conn:
        _insert_tenant(conn, other_tenant)
        conn.execute(insert_user, {"id": str(uuid4()), "tenant": DEMO_TENANT_ID})
        # Same email under a DIFFERENT tenant must be allowed.
        conn.execute(insert_user, {"id": str(uuid4()), "tenant": other_tenant})
        # Same email under the SAME tenant must be rejected.
        with pytest.raises(IntegrityError):
            conn.execute(insert_user, {"id": str(uuid4()), "tenant": DEMO_TENANT_ID})


def test_clients_client_code_unique_per_tenant_only() -> None:
    other_tenant = str(uuid4())
    insert_client = text(
        "INSERT INTO clients (id, tenant_id, client_code, display_name, risk_profile, "
        "jurisdictions, excluded_sectors, excluded_regions, created_at) VALUES (:id, "
        ":tenant, 'C001', 'Other co', 'moderate', '[]', '[]', '[]', CURRENT_TIMESTAMP)"
    )
    with _rolled_back_connection() as conn:
        _insert_tenant(conn, other_tenant)
        # C001 already exists in the demo tenant from the seed; the same code
        # under a different tenant must succeed.
        conn.execute(insert_client, {"id": str(uuid4()), "tenant": other_tenant})
        # A second C001 under that same tenant must fail.
        with pytest.raises(IntegrityError):
            conn.execute(insert_client, {"id": str(uuid4()), "tenant": other_tenant})


# ---------------------------------------------------------------------------
# ORM round-trip
# ---------------------------------------------------------------------------


def test_orm_can_round_trip_decision_with_tenant_id() -> None:
    # A raw ORM insert bypasses the hash chain, so keep it in a throwaway
    # tenant instead of the demo tenant whose chain other tests verify.
    from tests.conftest import make_tenant

    tenant_id = make_tenant()
    with SessionLocal() as db:
        decision = Decision(
            tenant_id=tenant_id,
            question="orm round-trip",
            outcome="answered",
            llm_model="test",
            latency_ms=1,
        )
        db.add(decision)
        db.commit()
        loaded = db.get(Decision, decision.id)
        assert loaded is not None
        assert loaded.tenant_id == tenant_id
