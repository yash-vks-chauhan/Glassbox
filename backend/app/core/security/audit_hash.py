"""Tamper-evident hash chain for the audit log.

For each ``decisions`` row we store:

- ``prev_hash`` — the ``row_hash`` of the *immediately preceding* decision in
  the same tenant (NULL for the genesis row).
- ``row_hash`` — ``sha256(prev_hash || canonical_json(this_row))``.

Why per-tenant? Tenants must not be able to observe each other's audit
volume, and one giant cross-tenant chain would let any single tenant's
verification depend on rows it can't see. Per-tenant chains are independent
and tenant-scoped; ``GET /audit/verify`` walks the caller's tenant chain
only.

Canonicalisation: ``sorted_keys`` + ``separators=(",", ":")`` + UTC ISO
timestamps. The fields participating in the hash are the *content* fields,
not derived metadata. Adding a new column later means either:

a) Include it in ``HASHED_FIELDS`` (which invalidates existing chains
   — only do this between data migrations), or
b) Leave it out (so it's correctly excluded from tamper detection).

Default-deny: never let the hash silently change shape. If a field is added
without a migration update, the verify endpoint will start reporting "first
break at decision X" — which is the right failure mode.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models_db import Decision, DecisionClaim, RetrievedChunk


# Fields participating in the hash for a Decision row. Order is irrelevant
# because we sort_keys at the JSON layer — but the *set* is part of the
# contract. Don't drop fields without bumping the chain version.
HASHED_DECISION_FIELDS = (
    "id",
    "tenant_id",
    "user_id",
    "created_at",
    "question",
    "client_id",
    "outcome",
    "final_answer",
    "determinism_score",
    "grounding_score",
    "llm_model",
    "latency_ms",
)
HASHED_CLAIM_FIELDS = (
    "id",
    "decision_id",
    "claim_text",
    "cited_source_id",
    "verified",
    "kept",
)
HASHED_CHUNK_FIELDS = (
    "id",
    "decision_id",
    "source_id",
    "source_type",
    "chunk_text",
    "score",
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # Normalise SQLite's naive datetimes so the canonical form is stable.
        return value.replace(microsecond=value.microsecond).isoformat() + "+00:00"
    return value.isoformat()


def _scalar(value: object) -> object:
    if isinstance(value, datetime):
        return _iso(value)
    return value


def canonical_dict(row: object, fields: Iterable[str]) -> dict[str, object]:
    return {name: _scalar(getattr(row, name, None)) for name in fields}


def canonical_decision_payload(
    decision: Decision,
    claims: Iterable[DecisionClaim] | None = None,
    chunks: Iterable[RetrievedChunk] | None = None,
) -> str:
    """Serialise the *content* of a decision (plus its claims and retrieved
    chunks) into a canonical JSON string. Sort everything we can so the
    output is deterministic regardless of row insert order."""
    payload = {
        "decision": canonical_dict(decision, HASHED_DECISION_FIELDS),
        "claims": sorted(
            (canonical_dict(c, HASHED_CLAIM_FIELDS) for c in (claims or [])),
            key=lambda d: d["id"],
        ),
        "chunks": sorted(
            (canonical_dict(c, HASHED_CHUNK_FIELDS) for c in (chunks or [])),
            key=lambda d: d["id"],
        ),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_row_hash(prev_hash: str | None, canonical_json: str) -> str:
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("utf-8"))
    h.update(b"\x1f")  # ASCII Unit Separator — unambiguous prev/canonical split
    h.update(canonical_json.encode("utf-8"))
    return h.hexdigest()


def latest_tail_hash(db: Session, *, tenant_id: str) -> str | None:
    """Return the ``row_hash`` of the most recent decision in the tenant's
    chain, or None if the tenant has no decisions yet."""
    row = db.scalar(
        select(Decision)
        .where(Decision.tenant_id == tenant_id)
        .where(Decision.row_hash.is_not(None))
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    )
    return row.row_hash if row else None


@dataclass(frozen=True)
class VerifyReport:
    tenant_id: str
    total: int
    verified: int
    first_break_decision_id: str | None
    first_break_reason: str | None
    tail_hash: str | None

    @property
    def ok(self) -> bool:
        return self.first_break_decision_id is None


def verify_chain(db: Session, *, tenant_id: str) -> VerifyReport:
    """Walk the tenant's decision chain in insert order and report the
    first break (if any). A "break" is any of:

    - Recomputed hash doesn't match ``row_hash``.
    - Stored ``prev_hash`` doesn't match the previous row's ``row_hash``.
    - A row's ``row_hash`` is NULL when an earlier row had one (gap).

    Legacy rows with both hash columns NULL are tolerated *only* at the
    head of the chain. Once any row has a hash, every subsequent row must.
    """
    rows = list(
        db.scalars(
            select(Decision)
            .where(Decision.tenant_id == tenant_id)
            .options(
                selectinload(Decision.claims),
                selectinload(Decision.retrieved_chunks),
            )
            .order_by(Decision.created_at.asc(), Decision.id.asc())
        )
    )
    total = len(rows)
    verified = 0
    chain_started = False
    expected_prev: str | None = None
    for row in rows:
        if row.row_hash is None and row.prev_hash is None and not chain_started:
            # Legacy row — accept and move on.
            verified += 1
            continue
        chain_started = True
        if row.row_hash is None or row.prev_hash is None:
            return VerifyReport(
                tenant_id=tenant_id,
                total=total,
                verified=verified,
                first_break_decision_id=row.id,
                first_break_reason="missing prev_hash or row_hash on chained row",
                tail_hash=expected_prev,
            )
        if row.prev_hash != (expected_prev or ""):
            return VerifyReport(
                tenant_id=tenant_id,
                total=total,
                verified=verified,
                first_break_decision_id=row.id,
                first_break_reason="prev_hash does not match prior row_hash",
                tail_hash=expected_prev,
            )
        canonical = canonical_decision_payload(row, row.claims, row.retrieved_chunks)
        computed = compute_row_hash(row.prev_hash, canonical)
        if computed != row.row_hash:
            return VerifyReport(
                tenant_id=tenant_id,
                total=total,
                verified=verified,
                first_break_decision_id=row.id,
                first_break_reason="row content mutated since hash was recorded",
                tail_hash=expected_prev,
            )
        verified += 1
        expected_prev = row.row_hash
    return VerifyReport(
        tenant_id=tenant_id,
        total=total,
        verified=verified,
        first_break_decision_id=None,
        first_break_reason=None,
        tail_hash=expected_prev,
    )
