from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np

from app.config import get_settings


class Embedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class HashEmbedder(Embedder):
    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _tokens(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest, "big") % self.dimensions
                vectors[row, index] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


def _tokens(text: str) -> list[str]:
    clean = []
    token = []
    for char in text.lower():
        if char.isalnum() or char in {"%", "_"}:
            token.append(char)
        elif token:
            clean.append("".join(token))
            token = []
    if token:
        clean.append("".join(token))
    return clean


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_backend.lower() in {"sentence-transformers", "bge"}:
        try:
            return SentenceTransformerEmbedder(settings.embed_model)
        except Exception:
            return HashEmbedder()
    return HashEmbedder()


def embed_texts(texts: list[str]) -> np.ndarray:
    return get_embedder().encode(texts)


def cosine_similarity(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return np.asarray([], dtype=np.float32)
    return matrix @ query_vector.reshape(-1)
