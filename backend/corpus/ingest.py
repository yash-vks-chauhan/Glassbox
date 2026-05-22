from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from app.config import BACKEND_DIR, get_settings
from app.core.embeddings import embed_texts


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


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


def source_info(path: Path, metadata: dict[str, object]) -> tuple[str, str]:
    parent = path.parent.name
    if parent == "ips":
        return str(metadata.get("client_id") or path.stem), "ips"
    if parent == "factsheets":
        return str(metadata.get("fund_id") or path.stem), "factsheet"
    return str(metadata.get("regulation_id") or path.stem), "regulation"


def build_chunks() -> list[dict[str, object]]:
    corpus_dir = BACKEND_DIR / "corpus"
    files = sorted(
        list((corpus_dir / "ips").glob("*.md"))
        + list((corpus_dir / "factsheets").glob("*.md"))
        + list((corpus_dir / "regulations").glob("*.md"))
    )
    chunks: list[dict[str, object]] = []
    for path in files:
        metadata, body = parse_metadata(path.read_text(encoding="utf-8"))
        source_id, source_type = source_info(path, metadata)
        for index, chunk in enumerate(chunk_body(body)):
            chunks.append(
                {
                    "source_id": source_id,
                    "source_type": source_type,
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
