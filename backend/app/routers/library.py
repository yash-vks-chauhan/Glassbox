"""The approved document set: GET /library and GET /library/{source_id}."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth.deps import current_user
from app.core.library import (
    LibraryDocument,
    citing_decisions,
    documents_for_tenant,
    find_document,
    indexed_passages,
)
from app.db import get_db
from app.models_db import User
from app.schemas import LibraryDocumentDetail, LibraryDocumentOut
from corpus.ingest import UnsafeSourceIdError, assert_safe_source_id


router = APIRouter(prefix="/library", tags=["library"])


def _out(doc: LibraryDocument, passages: int) -> dict:
    return {
        "source_id": doc.source_id,
        "source_type": doc.source_type,
        "title": doc.title,
        "shared": doc.shared,
        "file": doc.file,
        "version": doc.version,
        "updated_on": doc.updated_on,
        "size_bytes": doc.size_bytes,
        "indexed_passages": passages,
    }


@router.get("", response_model=list[LibraryDocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[LibraryDocumentOut]:
    passages = indexed_passages(user.tenant_id)
    return [
        LibraryDocumentOut(**_out(doc, passages.get(doc.source_id, 0)))
        for doc in documents_for_tenant(db, user.tenant_id)
    ]


@router.get("/{source_id}", response_model=LibraryDocumentDetail)
def get_document(
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> LibraryDocumentDetail:
    try:
        assert_safe_source_id(source_id)
    except UnsafeSourceIdError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    doc = find_document(db, user.tenant_id, source_id)
    if doc is None:
        # Another tenant's document looks exactly like a missing one.
        raise HTTPException(status_code=404, detail="Document not found")
    passages = indexed_passages(user.tenant_id).get(doc.source_id, 0)
    return LibraryDocumentDetail(
        **_out(doc, passages),
        metadata=doc.metadata,
        body=doc.body,
        cited_in_decisions=citing_decisions(db, user.tenant_id, doc.source_id),
    )
