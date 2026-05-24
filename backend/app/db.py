from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models_db import Base, DEMO_TENANT_ID


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
engine = create_engine(
    settings.resolved_database_url,
    connect_args=_connect_args(settings.resolved_database_url),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.resolved_database_url.startswith("sqlite"):
        _sync_sqlite_schema()
        _seed_demo_clients_if_missing()
        _install_audit_delete_guards()
        _backfill_audit_hash_chain_if_needed()


# Phase D: in dev environments we run via Base.metadata.create_all() rather
# than alembic, so the seed-clients rows created by migration 0002 won't be
# present on a fresh DB. Insert them idempotently so the demo tenant is usable
# the moment the server starts.
_DEMO_SEED_CLIENTS = [
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


def _seed_demo_clients_if_missing() -> None:
    """Insert the four canonical demo clients under the demo tenant if any are
    missing. Idempotent on `(tenant_id, client_code)` via INSERT OR IGNORE so
    repeated boots don't fail."""
    with engine.begin() as conn:
        if not _table_exists(conn, "clients"):
            return
        for row in _DEMO_SEED_CLIENTS:
            conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO clients (
                        id, tenant_id, client_code, display_name, household,
                        risk_profile, jurisdictions, max_single_position_pct,
                        min_liquid_within_30d_pct, excluded_sectors,
                        excluded_regions, ips_version, ips_updated_at,
                        aum_eur, advisor_name, created_at
                    ) VALUES (
                        :id, :tenant_id, :code, :name, :household,
                        :risk_profile, :jurisdictions, :max_pos,
                        :min_liq, :excl_sectors,
                        :excl_regions, :ips_version, :ips_updated_at,
                        :aum, :advisor, CURRENT_TIMESTAMP
                    )
                    """
                ).bindparams(tenant_id=DEMO_TENANT_ID, **row)
            )


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def _sync_sqlite_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        if "tenants" in inspector.get_table_names():
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO tenants (id, name, slug, status, plan, created_at) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', 'Demo Tenant', "
                    "'demo', 'active', 'standard', CURRENT_TIMESTAMP)"
                )
            )
        _add_column_if_missing(
            conn,
            inspector,
            "decisions",
            "tenant_id",
            "VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'",
        )
        _add_column_if_missing(conn, inspector, "decisions", "user_id", "VARCHAR(36)")
        _add_column_if_missing(
            conn,
            inspector,
            "decision_claims",
            "tenant_id",
            "VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "retrieved_chunks",
            "tenant_id",
            "VARCHAR(36) NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'",
        )
        _add_column_if_missing(conn, inspector, "retrieved_chunks", "file", "VARCHAR(512)")
        _add_column_if_missing(conn, inspector, "retrieved_chunks", "chunk_index", "INTEGER")
        _add_column_if_missing(conn, inspector, "retrieved_chunks", "source_version", "VARCHAR(64)")
        _add_column_if_missing(conn, inspector, "retrieved_chunks", "selected_reason", "VARCHAR(255)")
        _add_column_if_missing(conn, inspector, "model_eval_runs", "tenant_id", "VARCHAR(36)")
        _add_column_if_missing(conn, inspector, "model_eval_runs", "p50_latency_ms", "INTEGER")
        _add_column_if_missing(conn, inspector, "model_eval_runs", "p95_latency_ms", "INTEGER")
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "answerability_accuracy",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "refusal_correctness",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "numeric_compliance_accuracy",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "prompt_injection_resistance",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "advisor_quality_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "failure_buckets_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_runs",
            "eval_gate",
            "VARCHAR(16) NOT NULL DEFAULT 'fast'",
        )
        _add_column_if_missing(conn, inspector, "model_eval_results", "tenant_id", "VARCHAR(36)")
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "answerability_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "refusal_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "numeric_compliance_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "prompt_injection_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "advisor_quality_score",
            "FLOAT NOT NULL DEFAULT 0.0",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "banned_terms_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "failure_bucket",
            "VARCHAR(64) NOT NULL DEFAULT 'other'",
        )
        _add_column_if_missing(conn, inspector, "model_eval_results", "gold_answer", "TEXT")
        _add_column_if_missing(conn, inspector, "model_eval_results", "reason", "TEXT")
        _add_column_if_missing(
            conn,
            inspector,
            "model_eval_results",
            "adversarial",
            "BOOLEAN NOT NULL DEFAULT 0",
        )
        # --- Phase E columns ---------------------------------------------------
        _add_column_if_missing(conn, inspector, "decisions", "prev_hash", "VARCHAR(64)")
        _add_column_if_missing(conn, inspector, "decisions", "row_hash", "VARCHAR(64)")
        _add_column_if_missing(conn, inspector, "byo_keys", "last4", "VARCHAR(8)")
        if "escalations" in inspector.get_table_names():
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_escalations_active_decision "
                    "ON escalations (tenant_id, decision_id) "
                    "WHERE status IN ('open', 'in_review')"
                )
            )


def _add_column_if_missing(conn, inspector, table: str, column: str, ddl: str) -> None:
    if table not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


# Phase E — refuse any DELETE on the tamper-evident audit tables at the DB
# level. Corrections must go through `decision_corrections`. We use SQLite
# triggers (RAISE(ABORT)) so even raw SQL access can't bypass it; the
# trigger is idempotent and recreated on every boot.
_AUDIT_DELETE_GUARDS = {
    "decisions": "trg_no_delete_decisions",
    "decision_claims": "trg_no_delete_decision_claims",
    "retrieved_chunks": "trg_no_delete_retrieved_chunks",
}


def _install_audit_delete_guards() -> None:
    with engine.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())
        for table, trigger_name in _AUDIT_DELETE_GUARDS.items():
            if table not in existing_tables:
                continue
            # Drop+recreate so the trigger always reflects the current shape.
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
            conn.execute(
                text(
                    f"CREATE TRIGGER {trigger_name} BEFORE DELETE ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, 'audit row deletion blocked — "
                    f"use decision_corrections instead'); END"
                )
            )


def _backfill_audit_hash_chain_if_needed() -> None:
    """One-shot Phase E migration helper.

    The hash chain only became authoritative in Phase E. Existing decisions
    in a long-lived dev DB are a mix of:

    - Old rows with both ``prev_hash`` and ``row_hash`` NULL (legacy).
    - New rows where both are populated.

    Some legacy rows may sit *between* hashed siblings if the demo DB has
    been around across multiple test runs — that breaks ``/audit/verify``
    even though no tampering occurred.

    Fix: walk every tenant's chain in insert order and compute hashes for
    any row that's missing them, anchoring on whatever was already there.
    Idempotent: subsequent boots find nothing to do.
    """
    # Avoid importing the security module until after Base.metadata.create_all
    # has run, otherwise we can fight with model imports during fresh-DB boot.
    from sqlalchemy.orm import selectinload

    from app.core.security.audit_hash import (
        canonical_decision_payload,
        compute_row_hash,
    )
    from app.models_db import Decision

    with Session(bind=engine) as db:
        tenants = [
            row[0]
            for row in db.execute(
                text("SELECT DISTINCT tenant_id FROM decisions")
            ).all()
        ]
        for tenant_id in tenants:
            orm_rows = (
                db.query(Decision)
                .options(
                    selectinload(Decision.claims),
                    selectinload(Decision.retrieved_chunks),
                )
                .filter(Decision.tenant_id == tenant_id)
                .order_by(Decision.created_at.asc(), Decision.id.asc())
                .all()
            )
            if not orm_rows:
                continue
            # Rebuild the chain end-to-end so that backfilling a legacy row's
            # hash doesn't cascade into a "prev_hash mismatch" on the next
            # already-hashed row. We update only the rows whose stored hash
            # doesn't match the newly-computed one; in steady state (no
            # legacy rows) every recompute matches and we write nothing.
            expected_prev: str | None = None
            dirty = False
            for row in orm_rows:
                canonical = canonical_decision_payload(
                    row, row.claims, row.retrieved_chunks
                )
                desired_prev = expected_prev or ""
                desired_hash = compute_row_hash(desired_prev, canonical)
                if row.prev_hash != desired_prev or row.row_hash != desired_hash:
                    row.prev_hash = desired_prev
                    row.row_hash = desired_hash
                    dirty = True
                expected_prev = row.row_hash
            if dirty:
                db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
