from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from app.config import BACKEND_DIR, get_settings
from app.core.embeddings import embed_texts


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Phase D: every chunk is tagged with the conceptual Chroma collection it
# belongs to. Retrieval unions `SHARED_COLLECTION` with the caller's
# `glassbox_t_{tenant_id}`. The "" tenant_id sentinel marks a shared chunk
# so the existing _matches_tenant filter still works without changes.
SHARED_COLLECTION = "glassbox_shared"
SHARED_TENANT_SENTINEL = ""


def tenant_collection(tenant_id: str) -> str:
    return f"glassbox_t_{tenant_id}"


# Source-id syntax: alphanumerics, dashes, underscores, and dots. Anything
# outside this set (path separators, ".." segments, absolute paths) gets
# rejected at ingest time so a poisoned filename can't surface as a fake
# source_id at retrieval time or escape the corpus root.
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class UnsafeSourceIdError(ValueError):
    """Raised when a corpus file or caller hands us a source_id that contains
    path-traversal sequences, slashes, or other unsafe characters."""


def assert_safe_source_id(source_id: str) -> str:
    """Reject any source_id that contains `..`, path separators, or other
    characters outside the allowlist. Returns the source_id unchanged on
    success so call sites can wrap a value inline."""
    if not isinstance(source_id, str) or not _SAFE_SOURCE_ID.match(source_id):
        raise UnsafeSourceIdError(
            f"Unsafe source_id rejected (contains path traversal or invalid "
            f"characters): {source_id!r}"
        )
    if ".." in source_id:
        raise UnsafeSourceIdError(f"source_id may not contain '..': {source_id!r}")
    return source_id


def parse_metadata(raw: str) -> tuple[dict[str, object], str]:
    if raw.startswith("---"):
        _, meta_raw, body = raw.split("---", 2)
        return _parse_simple_yaml(meta_raw), body.strip()

    metadata: dict[str, object] = {}
    body_lines: list[str] = []
    for line in raw.splitlines():
        if ":" in line and not line.startswith("#") and not body_lines:
            key, value = line.split(":", 1)
            metadata[key.strip()] = _parse_value(value.strip())
        else:
            body_lines.append(line)
    return metadata, "\n".join(body_lines).strip()


def _parse_simple_yaml(raw: str) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for line in raw.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_value(value.strip())
    return metadata


def _parse_value(value: str) -> object:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("'\"") for part in inner.split(",")]
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value.strip("'\"")


def chunk_body(body: str) -> list[str]:
    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith("#"):
            continue
        sentences = [s.strip() for s in SENTENCE_RE.split(paragraph) if s.strip()]
        chunks.extend(sentences or [paragraph])
    return chunks


def _classify(path: Path) -> tuple[str, str, str]:
    """Return (source_type, tenant_id, collection) for a corpus file based on
    its location under backend/corpus/. Phase D layout:

      corpus/shared/regulations/*.md     -> shared regulation
      corpus/shared/factsheets/*.md      -> shared factsheet
      corpus/tenants/{tenant_id}/ips/*   -> tenant-owned IPS

    A file that doesn't match any of these patterns is skipped by the caller.
    """
    parts = path.parts
    # Match against the segment *after* backend/corpus/ so we don't depend on
    # the absolute path of the repo.
    try:
        anchor = parts.index("corpus")
    except ValueError:
        return ("unknown", SHARED_TENANT_SENTINEL, SHARED_COLLECTION)
    rel = parts[anchor + 1 :]

    if len(rel) >= 3 and rel[0] == "shared":
        sub = rel[1]
        if sub == "regulations":
            return ("regulation", SHARED_TENANT_SENTINEL, SHARED_COLLECTION)
        if sub == "factsheets":
            return ("factsheet", SHARED_TENANT_SENTINEL, SHARED_COLLECTION)

    if len(rel) >= 4 and rel[0] == "tenants" and rel[2] == "ips":
        tenant_id = rel[1]
        return ("ips", tenant_id, tenant_collection(tenant_id))

    return ("unknown", SHARED_TENANT_SENTINEL, SHARED_COLLECTION)


def _resolved_source_id(path: Path, metadata: dict[str, object], source_type: str) -> str:
    key = {
        "ips": "client_id",
        "factsheet": "fund_id",
        "regulation": "regulation_id",
    }.get(source_type)
    candidate = str(metadata.get(key)) if key and metadata.get(key) else path.stem
    return assert_safe_source_id(candidate)


def build_chunks() -> list[dict[str, object]]:
    corpus_dir = BACKEND_DIR / "corpus"
    # Shared content: regulations + factsheets.
    shared_files = sorted(
        list((corpus_dir / "shared" / "regulations").glob("*.md"))
        + list((corpus_dir / "shared" / "factsheets").glob("*.md"))
    )
    # Tenant content: every tenant directory contributes its own IPS files.
    tenant_root = corpus_dir / "tenants"
    tenant_files: list[Path] = []
    if tenant_root.is_dir():
        for tenant_dir in sorted(tenant_root.iterdir()):
            if not tenant_dir.is_dir():
                continue
            # Path-traversal guard: a tenant directory must be exactly one path
            # segment (no symlinks pointing outside the corpus root).
            if ".." in tenant_dir.parts or tenant_dir.is_symlink():
                continue
            ips_dir = tenant_dir / "ips"
            if ips_dir.is_dir():
                tenant_files.extend(sorted(ips_dir.glob("*.md")))

    chunks: list[dict[str, object]] = []
    for path in shared_files + tenant_files:
        metadata, body = parse_metadata(path.read_text(encoding="utf-8"))
        source_type, tenant_id, collection = _classify(path)
        if source_type == "unknown":
            continue
        # The IPS frontmatter may declare its own tenant_id (useful when a
        # tenant intentionally shares a doc across orgs). The path is the
        # ground truth though — never let metadata override the filesystem
        # assignment, otherwise a malicious IPS file could re-tag itself
        # into another tenant.
        try:
            source_id = _resolved_source_id(path, metadata, source_type)
        except UnsafeSourceIdError:
            # Skip the file; an operator can re-ingest after fixing.
            continue
        for index, chunk in enumerate(chunk_body(body)):
            chunks.append(
                {
                    "source_id": source_id,
                    "source_type": source_type,
                    "tenant_id": tenant_id,
                    "collection": collection,
                    "file": str(path.relative_to(BACKEND_DIR)),
                    "chunk_index": index,
                    "chunk_text": chunk,
                    "metadata": metadata,
                }
            )
    return chunks


def ingest() -> int:
    settings = get_settings()
    store_dir = settings.resolved_chroma_dir
    store_dir.mkdir(parents=True, exist_ok=True)
    chunks = build_chunks()
    texts = [str(chunk["chunk_text"]) for chunk in chunks]
    vectors = embed_texts(texts) if texts else np.zeros((0, 512), dtype=np.float32)
    (store_dir / "chunks.json").write_text(
        json.dumps(chunks, indent=2), encoding="utf-8"
    )
    np.save(store_dir / "vectors.npy", vectors)
    return len(chunks)


def main() -> None:
    count = ingest()
    print(f"Ingested {count} chunks into {get_settings().resolved_chroma_dir}")


if __name__ == "__main__":
    main()
