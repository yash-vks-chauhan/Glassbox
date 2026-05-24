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

import sqlite3

import pytest
from sqlalchemy import inspect, select

from app.db import SessionLocal, engine
from app.models_db import (
    DEMO_TENANT_ID,
    ClientRecord,
    Decision,
    Tenant,
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


def test_legacy_audit_rows_belong_to_demo_tenant() -> None:
    with engine.connect() as conn:
        # All pre-existing decisions should now point at the demo tenant.
        rows = conn.exec_driver_sql(
            "SELECT DISTINCT tenant_id FROM decisions"
        ).all()
    distinct = {r[0] for r in rows}
    assert DEMO_TENANT_ID in distinct
    # Other tenants may appear later as tests create them, but right after the
    # migration the only tenant present should be the demo one.
    assert distinct == {DEMO_TENANT_ID}


@pytest.mark.parametrize(
    "table",
    ["decisions", "decision_claims", "retrieved_chunks"],
)
def test_inserting_a_row_without_tenant_id_is_rejected(table: str) -> None:
    """The schema must reject any direct INSERT that omits tenant_id."""
    raw = sqlite3.connect(engine.url.database)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            if table == "decisions":
                raw.execute(
                    "INSERT INTO decisions (id, created_at, question, outcome, llm_model, latency_ms) "
                    "VALUES ('test-x', CURRENT_TIMESTAMP, 'q', 'answered', 'm', 0)"
                )
            elif table == "decision_claims":
                # First make a parent decision row that DOES carry tenant_id
                # so we hit the claims constraint, not the decision one.
                raw.execute(
                    "INSERT INTO decisions (id, tenant_id, created_at, question, outcome, llm_model, latency_ms) "
                    "VALUES ('test-y', ?, CURRENT_TIMESTAMP, 'q', 'answered', 'm', 0)",
                    (DEMO_TENANT_ID,),
                )
                raw.execute(
                    "INSERT INTO decision_claims (id, decision_id, claim_text, verified, kept) "
                    "VALUES ('claim-y', 'test-y', 'c', 0, 0)"
                )
            else:  # retrieved_chunks
                raw.execute(
                    "INSERT INTO decisions (id, tenant_id, created_at, question, outcome, llm_model, latency_ms) "
                    "VALUES ('test-z', ?, CURRENT_TIMESTAMP, 'q', 'answered', 'm', 0)",
                    (DEMO_TENANT_ID,),
                )
                raw.execute(
                    "INSERT INTO retrieved_chunks (id, decision_id, source_id, source_type, chunk_text, score) "
                    "VALUES ('ch-z', 'test-z', 's', 'ips', 't', 0.0)"
                )
            raw.commit()
    finally:
        # Roll back anything the parametrized test created so the next case
        # starts clean.
        raw.rollback()
        raw.execute("DELETE FROM retrieved_chunks WHERE id LIKE 'ch-%'")
        raw.execute("DELETE FROM decision_claims WHERE id LIKE 'claim-%'")
        raw.execute("DELETE FROM decisions WHERE id LIKE 'test-%'")
        raw.commit()
        raw.close()


# ---------------------------------------------------------------------------
# Uniqueness invariants
# ---------------------------------------------------------------------------


def test_users_email_unique_per_tenant_only() -> None:
    """Same email may exist across tenants, but not twice within one tenant."""
    raw = sqlite3.connect(engine.url.database)
    try:
        # Insert a second tenant for the cross-tenant assertion.
        raw.execute(
            "INSERT OR IGNORE INTO tenants (id, name, slug, status, plan, created_at) "
            "VALUES ('t-other', 'Other', 'other', 'active', 'standard', CURRENT_TIMESTAMP)"
        )
        raw.execute(
            "INSERT INTO users (id, tenant_id, email, password_hash, role, "
            "mfa_enrolled, email_verified, failed_login_count, created_at) "
            "VALUES ('u1', ?, 'a@x.com', 'h', 'advisor', 0, 0, 0, CURRENT_TIMESTAMP)",
            (DEMO_TENANT_ID,),
        )
        # Same email under a DIFFERENT tenant must be allowed.
        raw.execute(
            "INSERT INTO users (id, tenant_id, email, password_hash, role, "
            "mfa_enrolled, email_verified, failed_login_count, created_at) "
            "VALUES ('u2', 't-other', 'a@x.com', 'h', 'advisor', 0, 0, 0, CURRENT_TIMESTAMP)"
        )
        raw.commit()
        # Same email under the SAME tenant must be rejected.
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO users (id, tenant_id, email, password_hash, role, "
                "mfa_enrolled, email_verified, failed_login_count, created_at) "
                "VALUES ('u3', ?, 'a@x.com', 'h', 'advisor', 0, 0, 0, CURRENT_TIMESTAMP)",
                (DEMO_TENANT_ID,),
            )
            raw.commit()
    finally:
        raw.rollback()
        raw.execute("DELETE FROM users WHERE id IN ('u1','u2','u3')")
        raw.execute("DELETE FROM tenants WHERE id = 't-other'")
        raw.commit()
        raw.close()


def test_clients_client_code_unique_per_tenant_only() -> None:
    raw = sqlite3.connect(engine.url.database)
    try:
        raw.execute(
            "INSERT OR IGNORE INTO tenants (id, name, slug, status, plan, created_at) "
            "VALUES ('t-other2', 'Other2', 'other2', 'active', 'standard', CURRENT_TIMESTAMP)"
        )
        # C001 already exists in demo tenant from the seed; inserting it under
        # a different tenant must succeed.
        raw.execute(
            "INSERT INTO clients (id, tenant_id, client_code, display_name, "
            "risk_profile, jurisdictions, excluded_sectors, excluded_regions, "
            "created_at) "
            "VALUES ('c-x', 't-other2', 'C001', 'Other co', 'moderate', "
            "'[]', '[]', '[]', CURRENT_TIMESTAMP)"
        )
        raw.commit()
        # Inserting C001 a second time under the same other-tenant must fail.
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO clients (id, tenant_id, client_code, display_name, "
                "risk_profile, jurisdictions, excluded_sectors, excluded_regions, "
                "created_at) "
                "VALUES ('c-y', 't-other2', 'C001', 'Dup', 'moderate', "
                "'[]', '[]', '[]', CURRENT_TIMESTAMP)"
            )
            raw.commit()
    finally:
        raw.rollback()
        raw.execute("DELETE FROM clients WHERE id IN ('c-x','c-y')")
        raw.execute("DELETE FROM tenants WHERE id = 't-other2'")
        raw.commit()
        raw.close()


# ---------------------------------------------------------------------------
# ORM round-trip
# ---------------------------------------------------------------------------


def test_orm_can_round_trip_decision_with_tenant_id() -> None:
    decision_id: str
    with SessionLocal() as db:
        decision = Decision(
            tenant_id=DEMO_TENANT_ID,
            question="orm round-trip",
            outcome="answered",
            llm_model="test",
            latency_ms=1,
        )
        db.add(decision)
        db.commit()
        loaded = db.get(Decision, decision.id)
        assert loaded is not None
        assert loaded.tenant_id == DEMO_TENANT_ID
        decision_id = loaded.id

    # Phase E blocks ORM deletes on audit tables. Use the fixture cleanup
    # escape hatch here because this row is synthetic test data, not a product
    # decision that should stay in the hash chain.
    from tests.conftest import (
        _restore_audit_delete_guards,
        _suspend_audit_delete_guards,
    )

    raw = sqlite3.connect(engine.url.database)
    try:
        _suspend_audit_delete_guards(raw)
        raw.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
        _restore_audit_delete_guards(raw)
        raw.commit()
    finally:
        raw.close()
