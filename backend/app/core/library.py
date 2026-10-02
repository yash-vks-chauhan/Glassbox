"""The approved document set ("library") as each tenant sees it.

Documents come from the same files ingestion indexes (``corpus_files``), so
the library shows exactly what retrieval can cite: shared regulations and
factsheets plus the caller's own IPS documents and portfolio snapshots.
Lookups go through that list, never through a path built from user input.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.core.retrieval import _load_index
from app.models_db import ClientRecord, Decision, DecisionClaim
from corpus.ingest import (
    SHARED_TENANT_SENTINEL,
    UnsafeSourceIdError,
    classify_corpus_file,
    corpus_files,
    parse_metadata,
    resolve_source_id,
)


SOURCE_TYPES = ("ips", "portfolio", "factsheet", "regulation")
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class LibraryDocument:
    source_id: str
    source_type: str
    title: str
    shared: bool
    file: str
    version: str | None
    updated_on: str | None
    metadata: dict[str, object]
    body: str
    size_bytes: int


def _title(source_type: str, source_id: str, metadata: dict[str, object], body: str) -> str:
    if source_type == "factsheet" and metadata.get("name"):
        return f"{metadata['name']} ({source_id})"
    heading = _HEADING_RE.search(body)
    return heading.group(1).strip() if heading else source_id


def _as_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return None


def documents_for_tenant(db: Session, tenant_id: str) -> list[LibraryDocument]:
    """Shared documents plus this tenant's own, in a stable order."""
    clients = {
        row.client_code: row
        for row in db.scalars(select(ClientRecord).where(ClientRecord.tenant_id == tenant_id))
    }
    docs: list[LibraryDocument] = []
    for path in corpus_files():
        source_type, owner, _ = classify_corpus_file(path)
        if source_type not in SOURCE_TYPES:
            continue
        if owner != SHARED_TENANT_SENTINEL and owner != tenant_id:
            continue
        raw = path.read_text(encoding="utf-8")
        metadata, body = parse_metadata(raw)
        try:
            source_id = resolve_source_id(path, metadata, source_type)
        except UnsafeSourceIdError:
            continue
        version: str | None = None
        updated_on = _as_date(metadata.get("snapshot_date") or metadata.get("updated"))
        if source_type == "ips" and source_id in clients:
            client = clients[source_id]
            version = client.ips_version
            updated_on = _as_date(client.ips_updated_at) or updated_on
        if source_type == "portfolio":
            version = f"snapshot {updated_on}" if updated_on else None
        docs.append(
            LibraryDocument(
                source_id=source_id,
                source_type=source_type,
                title=_title(source_type, source_id, metadata, body),
                shared=owner == SHARED_TENANT_SENTINEL,
                file=str(Path(path).relative_to(BACKEND_DIR)),
                version=version or (str(metadata["version"]) if metadata.get("version") else None),
                updated_on=updated_on,
                metadata=metadata,
                body=body,
                size_bytes=len(raw.encode("utf-8")),
            )
        )
    order = {kind: i for i, kind in enumerate(SOURCE_TYPES)}
    return sorted(docs, key=lambda d: (order[d.source_type], d.source_id))


def find_document(db: Session, tenant_id: str, source_id: str) -> LibraryDocument | None:
    return next(
        (doc for doc in documents_for_tenant(db, tenant_id) if doc.source_id == source_id),
        None,
    )


def indexed_passages(tenant_id: str) -> Counter[str]:
    """How many indexed chunks each visible source id has."""
    chunks, _ = _load_index()
    return Counter(
        str(chunk["source_id"])
        for chunk in chunks
        if chunk.get("tenant_id") in (SHARED_TENANT_SENTINEL, None, tenant_id)
    )


def citing_decisions(db: Session, tenant_id: str, source_id: str) -> int:
    """Decisions in this tenant that kept at least one claim citing the source."""
    return db.scalar(
        select(func.count(func.distinct(DecisionClaim.decision_id)))
        .join(Decision, Decision.id == DecisionClaim.decision_id)
        .where(
            Decision.tenant_id == tenant_id,
            DecisionClaim.cited_source_id == source_id,
            DecisionClaim.kept.is_(True),
        )
    ) or 0
