from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.core.embeddings import cosine_similarity, embed_texts
from app.core.types import RetrievedChunk


def _store_paths() -> tuple[Path, Path]:
    store_dir = get_settings().resolved_chroma_dir
    return store_dir / "chunks.json", store_dir / "vectors.npy"


def ensure_index() -> None:
    chunks_path, vectors_path = _store_paths()
    if chunks_path.exists() and vectors_path.exists():
        return
    from corpus.ingest import ingest

    ingest()


def _load_index() -> tuple[list[dict[str, object]], np.ndarray]:
    ensure_index()
    chunks_path, vectors_path = _store_paths()
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    return chunks, vectors


def _matches_client(chunk: dict[str, object], client_id: str | None) -> bool:
    if client_id is None:
        return True
    if chunk.get("source_type") != "ips":
        return True
    return chunk.get("source_id") == client_id


def retrieve(question: str, client_id: str | None = None, k: int = 6) -> list[RetrievedChunk]:
    chunks, vectors = _load_index()
    allowed_indices = [
        index for index, chunk in enumerate(chunks) if _matches_client(chunk, client_id)
    ]
    if not allowed_indices:
        return []

    query_vector = embed_texts([_expanded_question(question)])[0]
    allowed_vectors = vectors[allowed_indices]
    scores = cosine_similarity(query_vector, allowed_vectors)
    ranked = sorted(
        zip(allowed_indices, scores.tolist()), key=lambda item: item[1], reverse=True
    )[:k]

    return [
        RetrievedChunk(
            source_id=str(chunks[index]["source_id"]),
            source_type=str(chunks[index]["source_type"]),
            chunk_text=str(chunks[index]["chunk_text"]),
            score=float(max(score, 0.0)),
            file=str(chunks[index].get("file") or ""),
            chunk_index=int(chunks[index].get("chunk_index") or 0),
        )
        for index, score in ranked
    ]


def _expanded_question(question: str) -> str:
    lower = question.lower()
    additions: list[str] = []
    if "%" in question or "percent" in lower:
        additions.append("single position limit concentration allocation")
    if "suitable" in lower or "suitability" in lower:
        additions.append("risk profile suitability recommendation")
    if "fund" in lower:
        additions.append("factsheet risk level asset class sector region")
    return f"{question} {' '.join(additions)}".strip()
