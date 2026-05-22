from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.llm import has_usable_openrouter_key
from app.main import _requests, app, settings as main_settings
from app.core.retrieval import retrieve
from corpus.ingest import ingest


@pytest.fixture(autouse=True)
def reset_rate_limit(monkeypatch):
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "1")
    get_settings.cache_clear()
    _requests.clear()
    main_settings.rate_limit_per_min = 100
    yield
    _requests.clear()
    main_settings.rate_limit_per_min = 100
    get_settings.cache_clear()


def client() -> TestClient:
    return TestClient(app)


def test_p1_retrieval():
    ingest()
    results = retrieve("single position limit", client_id="C001", k=3)
    assert any("25%" in result.chunk_text and "single position" in result.chunk_text.lower() for result in results)


def test_p2_grounding():
    ingest()
    with client() as test_client:
        response = test_client.post(
            "/ask",
            json={"question": "What is the single position limit for client C001?", "client_id": "C001"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] in {"answered", "fallback"}
    if payload["outcome"] == "answered":
        assert payload["citations"]
        source_ids = {citation["source_id"] for citation in payload["citations"]}
        assert all(f"[{source_id}]" in payload["answer"] for source_id in source_ids)


def test_p3_verify_refusal():
    ingest()
    with client() as test_client:
        tax = test_client.post(
            "/ask",
            json={"question": "What is the capital gains tax rate in Germany?", "client_id": "C001"},
        ).json()
        violation = test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
        ).json()
        suitability = test_client.post(
            "/ask",
            json={"question": "Is fund F100 suitable for client C001?", "client_id": "C001"},
        ).json()
    assert tax["outcome"] == "refused"
    assert violation["outcome"] == "flagged"
    assert "violates" in (violation["answer"] or "").lower()
    assert suitability["outcome"] in {"answered", "fallback"}


def test_p4_provenance():
    ingest()
    with client() as test_client:
        asked = test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
        ).json()
        audit = test_client.get(f"/audit/{asked['decision_id']}")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["question"]
    assert payload["retrieved_chunks"]
    assert "decision_claims" in payload


def test_p5_trust_and_fallback(monkeypatch):
    ingest()
    with client() as test_client:
        test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
        )
        metrics = test_client.get("/metrics/summary").json()
    assert metrics["hallucination_rate"] is not None
    assert metrics["flagged_rate"] is not None

    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with client() as test_client:
            payload = test_client.post(
                "/ask",
                json={"question": "Is fund F200 suitable for client C001?", "client_id": "C001"},
            ).json()
            fallback_violation = test_client.post(
                "/ask",
                json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
            ).json()
        assert payload["outcome"] == "fallback"
        assert fallback_violation["outcome"] == "flagged"
    finally:
        monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "1")
        get_settings.cache_clear()


def test_p6_determinism():
    ingest()
    with client() as test_client:
        response = test_client.post(
            "/determinism",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001", "runs": 3},
        )
    assert response.status_code == 200
    payload = response.json()
    assert 0.0 <= payload["determinism_score"] <= 1.0
    assert len(payload["per_run_outcomes"]) == 3


def test_p7_ratelimit():
    main_settings.rate_limit_per_min = 2
    _requests.clear()
    with client() as test_client:
        assert test_client.get("/metrics/summary").status_code == 200
        assert test_client.get("/metrics/summary").status_code == 200
        limited = test_client.get("/metrics/summary")
    assert limited.status_code == 429
    assert "busy" in limited.json()["detail"].lower()


def test_p8_openrouter_placeholder_key_is_not_usable():
    assert not has_usable_openrouter_key(None)
    assert not has_usable_openrouter_key("sk-or-...")
    assert has_usable_openrouter_key("sk-or-test-value-that-is-long-enough")
