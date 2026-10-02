"""The embedder falls back to hashes, and says so, when its backend can't load."""

from __future__ import annotations

import logging
import sys

from app.config import get_settings
from app.core import embeddings


def test_unavailable_sentence_transformers_falls_back_to_hash(monkeypatch, caplog):
    monkeypatch.setenv("GLASSBOX_EMBEDDING_BACKEND", "sentence-transformers")
    # None in sys.modules makes `import sentence_transformers` fail, as it
    # does when requirements-embeddings.txt isn't installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    get_settings.cache_clear()
    embeddings.get_embedder.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="app.core.embeddings"):
            embedder = embeddings.get_embedder()
        assert isinstance(embedder, embeddings.HashEmbedder)
        assert embedder.label == "hash"
        assert "embedding_backend_unavailable" in caplog.text
        assert embedder.encode(["fund F100"]).shape == (1, 512)
    finally:
        get_settings.cache_clear()
        embeddings.get_embedder.cache_clear()
