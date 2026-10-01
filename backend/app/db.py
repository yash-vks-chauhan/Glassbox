from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.audit_guards import install_audit_guards
from app.models_db import Base, ClientRecord, DEMO_TENANT_ID, Tenant


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


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        # WAL lets reads run alongside the single writer, and the busy timeout
        # makes a second writer wait instead of failing with "database is
        # locked" (e.g. a CLI script while the server is busy).
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def init_db() -> None:
    """Make the database usable on boot. Idempotent.

    Postgres deployments get their schema from ``alembic upgrade head``; the
    ``create_all`` here is a no-op for them. Local SQLite databases rely on
    ``create_all`` plus the column sync below.
    """
    Base.metadata.create_all(bind=engine)
    if is_sqlite():
        _sync_sqlite_schema()
    _seed_demo_tenant_if_missing()
    with engine.begin() as conn:
        install_audit_guards(conn)
    _backfill_audit_hash_chain_if_needed()


# The demo tenant owns the sample corpus under backend/corpus/tenants/<id>/.
# Migration 0002 seeds the same rows; this keeps databases built by
# create_all() usable the moment the server starts.
_DEMO_SEED_CLIENTS = [
    {
        "id": "11111111-1111-1111-1111-000000000001",
        "client_code": "C001",
        "display_name": "Müller Family Office",
        "household": "DACH · Zurich",
        "risk_profile": "moderate",
        "jurisdictions": ["CH", "US"],
        "max_single_position_pct": 25.0,
        "min_liquid_within_30d_pct": 15.0,
        "excluded_sectors": ["tobacco", "firearms"],
        "excluded_regions": ["russia"],
        "ips_version": "v3.2",
        "ips_updated_at": datetime(2024, 11, 18, tzinfo=timezone.utc),
        "aum_eur": 18_400_000,
        "advisor_name": "S. Kühn",
    },
    {
        "id": "11111111-1111-1111-1111-000000000002",
        "client_code": "C002",
        "display_name": "Vance Conservative Trust",
        "household": "US · Boston",
        "risk_profile": "conservative",
        "jurisdictions": ["US"],
        "max_single_position_pct": 15.0,
        "min_liquid_within_30d_pct": 30.0,
        "excluded_sectors": ["tobacco", "firearms", "gambling", "cryptocurrency"],
        "excluded_regions": ["russia", "sanctioned_markets"],
        "ips_version": "v2.7",
        "ips_updated_at": datetime(2025, 1, 9, tzinfo=timezone.utc),
        "aum_eur": 6_900_000,
        "advisor_name": "A. Lopez",
    },
    {
        "id": "11111111-1111-1111-1111-000000000003",
        "client_code": "C003",
        "display_name": "Tan Growth Mandate",
        "household": "APAC · Singapore",
        "risk_profile": "aggressive",
        "jurisdictions": ["CH", "SG"],
        "max_single_position_pct": 35.0,
        "min_liquid_within_30d_pct": 10.0,
        "excluded_sectors": ["tobacco"],
        "excluded_regions": ["russia"],
        "ips_version": "v4.0",
        "ips_updated_at": datetime(2025, 3, 2, tzinfo=timezone.utc),
        "aum_eur": 42_000_000,
        "advisor_name": "M. Reis",
    },
    {
        "id": "11111111-1111-1111-1111-000000000004",
        "client_code": "C004",
        "display_name": "Chauhan Growth Mandate",
        "household": "IN · Mumbai",
        "risk_profile": "moderate",
        "jurisdictions": ["IN", "SG"],
        "max_single_position_pct": 20.0,
        "min_liquid_within_30d_pct": 12.0,
        "excluded_sectors": ["cryptocurrency", "gambling"],
        "excluded_regions": ["russia"],
        "ips_version": "v1.1",
        "ips_updated_at": datetime(2026, 5, 22, tzinfo=timezone.utc),
        "aum_eur": 12_800_000,
        "advisor_name": "R. Mehta",
    },
]


def _seed_demo_tenant_if_missing() -> None:
    """Insert the demo tenant and its four sample clients when missing.
    Existing rows (matched on tenant id / client code) are never modified."""
    with Session(bind=engine) as db:
        if db.get(Tenant, DEMO_TENANT_ID) is None:
            db.add(Tenant(id=DEMO_TENANT_ID, name="Demo Tenant", slug="demo"))
            db.flush()
        existing_codes = set(
            db.scalars(
                select(ClientRecord.client_code).where(
                    ClientRecord.tenant_id == DEMO_TENANT_ID
                )
            )
        )
        for row in _DEMO_SEED_CLIENTS:
            if row["client_code"] not in existing_codes:
                db.add(ClientRecord(tenant_id=DEMO_TENANT_ID, **row))
        db.commit()


def _sync_sqlite_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
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
        _add_column_if_missing(conn, inspector, "decisions", "thread_id", "VARCHAR(36)")
        _add_column_if_missing(conn, inspector, "decisions", "retrieval_question", "TEXT")
        _add_column_if_missing(conn, inspector, "decisions", "refusal_reason", "TEXT")
        _add_column_if_missing(conn, inspector, "decisions", "prev_hash", "VARCHAR(64)")
        _add_column_if_missing(conn, inspector, "decisions", "row_hash", "VARCHAR(64)")
        _add_column_if_missing(conn, inspector, "byo_keys", "last4", "VARCHAR(8)")
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_decisions_thread_id ON decisions (thread_id)")
        )
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


def _backfill_audit_hash_chain_if_needed() -> None:
    """Link unhashed decisions into their tenant's chain without ever
    rewriting a hash that already exists.

    - A tenant whose rows predate the hash chain entirely (every ``row_hash``
      NULL) gets one chain computed from its first row. This is the one-time
      Phase E migration.
    - Unhashed rows *after* the last hashed row extend the chain from it.
    - Everything else is left alone. In particular a row whose content no
      longer matches its stored hash is *not* re-hashed: that mismatch is
      exactly the tampering ``GET /audit/verify`` must report, so healing it
      on boot would defeat the audit log.
    """
    # Imported late so a fresh-DB boot doesn't fight model imports.
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
                select(Decision.tenant_id).where(Decision.row_hash.is_(None)).distinct()
            ).all()
        ]
        for tenant_id in tenants:
            rows = (
                db.query(Decision)
                .options(
                    selectinload(Decision.claims),
                    selectinload(Decision.retrieved_chunks),
                )
                .filter(Decision.tenant_id == tenant_id)
                .order_by(Decision.created_at.asc(), Decision.id.asc())
                .all()
            )
            hashed_positions = [i for i, row in enumerate(rows) if row.row_hash is not None]
            if hashed_positions:
                start = hashed_positions[-1] + 1
                prev_hash = rows[hashed_positions[-1]].row_hash
            else:
                start = 0
                prev_hash = ""
            pending = rows[start:]
            if not pending:
                continue
            for row in pending:
                canonical = canonical_decision_payload(row, row.claims, row.retrieved_chunks)
                row.prev_hash = prev_hash
                row.row_hash = compute_row_hash(prev_hash, canonical)
                prev_hash = row.row_hash
            db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
