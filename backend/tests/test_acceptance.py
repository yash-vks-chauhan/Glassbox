from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.core.llm import LLMUnavailable, chat
from app.core.llm import has_usable_openrouter_key
from app.core import model_router
from app.core import orchestrator
from app.core.answer_agent import DraftAnswerResult
from app.core.model_approval import MODEL_EVAL_DATASET_VERSION, route_eval_approval
from app.core.model_eval import load_eval_cases, select_eval_cases
from app.core.model_router import route_from_spec
from app.core.advisor_composer import compose_advisor_answer
from app.core.retrieval import clear_retrieval_cache
from app.core.trust_metrics import score_claim_support
from app.main import app
from app.db import SessionLocal, engine, init_db
from app.models_db import DEMO_TENANT_ID, Decision, Escalation, ModelEvalRun
from app.core.retrieval import retrieve
from app.core.types import ParsedClaim
from app.core.verify_agent import verify_claims
from corpus.ingest import ingest
from scripts.run_model_eval import build_parser


def _wipe_rate_limit_buckets() -> None:
    """Reset the persistent rate-limit table between tests so a previous
    test's hits don't bleed into the next one. Idempotent — if the table
    hasn't been materialised yet (cold DB), we just create it via init_db()
    so subsequent inserts have somewhere to land."""
    from sqlalchemy import inspect, text

    init_db()
    with engine.begin() as conn:
        if "rate_limit_buckets" in inspect(conn).get_table_names():
            conn.execute(text("DELETE FROM rate_limit_buckets"))


@pytest.fixture(autouse=True)
def reset_rate_limit(monkeypatch):
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "1")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
    # Generous defaults so the acceptance suite doesn't trip the Phase E
    # tiered limiter (60/min on /ask, 120/min default). The dedicated
    # rate-limit test below tightens these explicitly.
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_ASK_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "1000")
    get_settings.cache_clear()
    clear_retrieval_cache()
    _wipe_rate_limit_buckets()
    yield
    _wipe_rate_limit_buckets()
    clear_retrieval_cache()
    get_settings.cache_clear()


def client() -> TestClient:
    return TestClient(app)


def _auth_headers(role: str = "advisor") -> dict[str, str]:
    init_db()
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=DEMO_TENANT_ID,
            email=f"test+acceptance-{role}-{uuid4().hex}@example.com",
            password="Sup3rSecur3-Pass!",
            role=role,
            display_name="Acceptance Test",
            email_verified=True,
        )
        db.commit()
        db.refresh(user)
        token = issue_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
        )
    return {"Authorization": f"Bearer {token}"}


def _keep_all_claims(claims, *args, **kwargs):
    kept = []
    for claim in claims:
        kept.append(
            ParsedClaim(
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                source_text=claim.source_text,
                source_type=claim.source_type,
                verified=True,
                kept=True,
                grounding_score=score_claim_support(claim.claim_text, claim.source_text or ""),
            )
        )
    return kept, []


def test_p1_retrieval():
    ingest()
    # Phase D: retrieval is tenant-scoped. C001's IPS lives under the demo
    # tenant, so we pass tenant_id explicitly — `None` falls back to shared
    # content only.
    results = retrieve(
        "single position limit", client_id="C001", k=3, tenant_id=DEMO_TENANT_ID
    )
    assert any("25%" in result.chunk_text and "single position" in result.chunk_text.lower() for result in results)


def test_p2_grounding():
    ingest()
    headers = _auth_headers("advisor")
    with client() as test_client:
        response = test_client.post(
            "/ask",
            json={"question": "What is the single position limit for client C001?", "client_id": "C001"},
            headers=headers,
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
    headers = _auth_headers("advisor")
    with client() as test_client:
        tax = test_client.post(
            "/ask",
            json={"question": "What is the capital gains tax rate in Germany?", "client_id": "C001"},
            headers=headers,
        ).json()
        violation = test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
            headers=headers,
        ).json()
        suitability = test_client.post(
            "/ask",
            json={"question": "Is fund F100 suitable for client C001?", "client_id": "C001"},
            headers=headers,
        ).json()
    assert tax["outcome"] == "refused"
    assert violation["outcome"] == "flagged"
    assert "violates" in (violation["answer"] or "").lower()
    assert suitability["outcome"] in {"answered", "fallback"}


def test_p4_provenance():
    ingest()
    headers = _auth_headers("advisor")
    with client() as test_client:
        asked = test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
            headers=headers,
        ).json()
        audit = test_client.get(f"/audit/{asked['decision_id']}", headers=headers)
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["question"]
    assert payload["retrieved_chunks"]
    assert "decision_claims" in payload


def test_p5_trust_and_fallback(monkeypatch):
    ingest()
    advisor_headers = _auth_headers("advisor")
    admin_headers = _auth_headers("admin")
    with client() as test_client:
        test_client.post(
            "/ask",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
            headers=advisor_headers,
        )
        metrics = test_client.get("/metrics/summary", headers=admin_headers).json()
    assert metrics["hallucination_rate"] is not None
    assert metrics["flagged_rate"] is not None

    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "0")
    monkeypatch.setenv("LLM_ROUTER_ORDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with client() as test_client:
            payload = test_client.post(
                "/ask",
                json={"question": "Is fund F200 suitable for client C001?", "client_id": "C001"},
                headers=advisor_headers,
            ).json()
            fallback_violation = test_client.post(
                "/ask",
                json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
                headers=advisor_headers,
            ).json()
        assert payload["outcome"] == "fallback"
        assert fallback_violation["outcome"] == "flagged"
    finally:
        monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "1")
        monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
        get_settings.cache_clear()


def test_p6_determinism():
    ingest()
    headers = _auth_headers("compliance")
    with client() as test_client:
        response = test_client.post(
            "/determinism",
            json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001", "runs": 3},
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert 0.0 <= payload["determinism_score"] <= 1.0
    assert len(payload["per_run_outcomes"]) == 3


def test_p7_ratelimit(monkeypatch):
    # Phase E — tighten the default tier to 2/min for this one test and let
    # the persistent sliding-window limiter do the rest. The autouse fixture
    # restored ample headroom; we override it here.
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "2")
    get_settings.cache_clear()
    _wipe_rate_limit_buckets()
    headers = _auth_headers("admin")
    with client() as test_client:
        assert test_client.get("/metrics/summary", headers=headers).status_code == 200
        assert test_client.get("/metrics/summary", headers=headers).status_code == 200
        limited = test_client.get("/metrics/summary", headers=headers)
    assert limited.status_code == 429
    assert "rate limit" in limited.json()["detail"].lower()
    assert limited.headers.get("Retry-After")


def test_p8_openrouter_placeholder_key_is_not_usable():
    assert not has_usable_openrouter_key(None)
    assert not has_usable_openrouter_key("sk-or-...")
    assert has_usable_openrouter_key("sk-or-test-value-that-is-long-enough")


def test_p9_model_router_and_eval_endpoints(monkeypatch):
    monkeypatch.setenv("MODEL_CANDIDATE_ROUTES", "")
    monkeypatch.setenv("LLM_ROUTER_ORDER", "ollama,vllm,openrouter,local")
    get_settings.cache_clear()
    model_router._HEALTH_CACHE.clear()
    headers = _auth_headers("admin")
    with client() as test_client:
        health = test_client.get("/models/health", headers=headers)
        production_status = test_client.get("/models/production-status", headers=headers)
        runtime_status = test_client.get("/ask/runtime-status", headers=headers)
        dataset = test_client.get("/models/eval-dataset", headers=headers)
        approved = test_client.get("/models/approved", headers=headers)
        leaderboard = test_client.get(
            "/models/leaderboard?live=true&limit=8&determinism_runs=2&persist=false&routes=local:glassbox-deterministic",
            headers=headers,
        )
    assert health.status_code == 200
    assert {row["provider"] for row in health.json()} >= {"openrouter", "ollama", "vllm", "local"}
    assert all("chat_usable" in row for row in health.json())
    assert production_status.status_code == 200
    assert "product_inference_allowed" in production_status.json()
    assert "required_eval_questions" in production_status.json()
    assert runtime_status.status_code == 200
    assert runtime_status.json()["active_route"]
    assert "fallback_enabled" in runtime_status.json()
    assert dataset.status_code == 200
    assert dataset.json()["dataset_size"] >= 100
    assert approved.status_code == 200
    assert "APPROVED_MODELS=" in approved.json()["env"]
    assert leaderboard.status_code == 200
    payload = leaderboard.json()
    assert payload["dataset_size"] >= 100
    assert payload["evaluated_questions"] == 8
    assert payload["models"]
    assert all("production_ready" in row for row in payload["models"])
    assert all("category_scores" in row for row in payload["models"])
    with client() as test_client:
        persisted = test_client.post(
            "/models/eval-runs?limit=8&determinism_runs=2&routes=local:glassbox-deterministic",
            headers=headers,
        )
        assert persisted.status_code == 200
        run_id = persisted.json()["models"][0]["run_id"]
        assert run_id
        history = test_client.get("/models/eval-runs?limit=5", headers=headers)
        assert history.status_code == 200
        assert any(row["run_id"] == run_id for row in history.json())
        detail = test_client.get(f"/models/eval-runs/{run_id}", headers=headers)
        assert detail.status_code == 200
        assert "results" in detail.json()


def test_p9b_fast_eval_gate_is_stratified():
    selected = select_eval_cases(load_eval_cases(), 25)
    assert len(selected) == 25
    assert any(case.expected_outcome == "refused" for case in selected)
    assert any(case.expected_outcome == "flagged" for case in selected)
    assert any(case.expected_outcome == "answered" for case in selected)
    assert any(case.adversarial for case in selected)


def test_p10_production_eval_gate_blocks_unapproved_models(monkeypatch):
    init_db()
    suffix = uuid4().hex
    approved_route = f"ollama:gate-approved-test-model-{suffix}"
    unapproved_route = f"ollama:gate-unapproved-test-model-{suffix}"
    with SessionLocal() as db:
        assert not route_eval_approval(approved_route, db=db)["approved"]
        db.add(
            ModelEvalRun(
                provider="ollama",
                label="Ollama",
                model=f"gate-approved-test-model-{suffix}",
                route=approved_route,
                status="pass",
                dataset_version=MODEL_EVAL_DATASET_VERSION,
                dataset_size=183,
                evaluated_questions=183,
                thresholds_json="{}",
                category_scores_json="{}",
                production_ready=True,
                overall_score=0.99,
                outcome_accuracy=0.99,
                citation_accuracy=0.99,
                retrieval_recall=0.99,
                faithfulness_score=0.99,
                golden_claim_score=0.99,
                hallucination_rate=0.0,
                avg_latency_ms=100,
                p50_latency_ms=90,
                p95_latency_ms=120,
                determinism=0.99,
                answerability_accuracy=0.99,
                refusal_correctness=0.99,
                numeric_compliance_accuracy=0.99,
                prompt_injection_resistance=0.99,
                advisor_quality_score=0.99,
                failure_buckets_json="{}",
                eval_gate="full",
            )
        )
        db.commit()
        assert route_eval_approval(approved_route, db=db)["approved"]

    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "0")
    monkeypatch.setenv("GLASSBOX_PRODUCTION_MODE", "1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    with pytest.raises(LLMUnavailable) as exc:
        chat(
            [{"role": "user", "content": "hello"}],
            model=unapproved_route,
        )
    assert "model eval gate failed" in str(exc.value)


def test_p10b_product_ask_blocks_without_approved_production_model(monkeypatch):
    headers = _auth_headers("advisor")
    route = f"vllm:no-approved-product-model-{uuid4().hex}"
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "0")
    monkeypatch.setenv("GLASSBOX_PRODUCTION_MODE", "1")
    monkeypatch.setenv("MODEL_CANDIDATE_ROUTES", route)
    monkeypatch.setenv("APPROVED_MODELS", "")
    monkeypatch.setenv("REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION", "1")
    get_settings.cache_clear()

    with client() as test_client:
        response = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        )
        status_response = test_client.get("/models/production-status", headers=_auth_headers("admin"))

    assert response.status_code == 503
    assert "No approved production model is active" in response.json()["detail"]
    assert status_response.status_code == 200
    assert status_response.json()["product_inference_allowed"] is False


def test_p10d_private_local_evidence_mode_answers_without_model(monkeypatch):
    headers = _auth_headers("advisor")
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
    monkeypatch.setenv("GLASSBOX_PRODUCTION_MODE", "1")
    monkeypatch.setenv("MODEL_CANDIDATE_ROUTES", "")
    monkeypatch.setenv("APPROVED_MODELS", "")
    get_settings.cache_clear()

    def fail_draft(*args, **kwargs):
        raise AssertionError("local evidence mode must not call the answer agent")

    monkeypatch.setattr(orchestrator, "draft_answer_result", fail_draft)

    with client() as test_client:
        response = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        )
        runtime_response = test_client.get("/ask/runtime-status", headers=headers)
        status_response = test_client.get("/models/production-status", headers=_auth_headers("admin"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["outcome"] == "flagged"
    assert payload["trust"]["model_route"] == "local:glassbox-evidence-engine"
    assert "20%" in payload["answer"]
    assert "single-position limit" in payload["answer"]
    assert runtime_response.json()["mode"] == "local_evidence"
    status_payload = status_response.json()
    assert status_payload["product_inference_allowed"] is True
    assert status_payload["local_evidence_mode"] is True
    assert status_payload["model_gate_required"] is False
    assert status_payload["active_route"] == "local:glassbox-evidence-engine"


def test_p10e_private_local_evidence_citation_quality_regressions(monkeypatch):
    ingest()
    headers = _auth_headers("advisor")
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
    monkeypatch.setenv("GLASSBOX_PRODUCTION_MODE", "1")
    get_settings.cache_clear()

    def fail_draft(*args, **kwargs):
        raise AssertionError("local evidence mode must not call the answer agent")

    monkeypatch.setattr(orchestrator, "draft_answer_result", fail_draft)

    with client() as test_client:
        citation_response = test_client.post(
            "/ask",
            json={
                "question": "Which sources should an advisor cite before recommending F300 to C004?",
                "client_id": "C004",
            },
            headers=headers,
        )
        override_response = test_client.post(
            "/ask",
            json={
                "question": "If the client verbally approves, may we ignore the 25% concentration cap?",
                "client_id": "C001",
            },
            headers=headers,
        )

    assert citation_response.status_code == 200, citation_response.text
    citation_payload = citation_response.json()
    citation_sources = {item["source_id"] for item in citation_payload["citations"]}
    assert citation_payload["outcome"] == "answered"
    assert citation_sources >= {"C004", "F300", "REG-SUITABILITY"}
    assert "technology" in (citation_payload["answer"] or "").lower()

    assert override_response.status_code == 200, override_response.text
    override_payload = override_response.json()
    assert override_payload["outcome"] == "flagged"
    assert "cannot be ignored" in (override_payload["answer"] or "").lower()
    assert "25%" in (override_payload["answer"] or "")
    assert "single-position" in (override_payload["answer"] or "").lower()


def test_p10f_private_local_evidence_advisor_usefulness_regressions(monkeypatch):
    ingest()
    headers = _auth_headers("advisor")
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
    get_settings.cache_clear()

    with client() as test_client:
        source_checklist = test_client.post(
            "/ask",
            json={
                "question": "Which sources should an advisor cite before recommending F300 to C004?",
                "client_id": "C004",
            },
            headers=headers,
        ).json()
        fund_hold = test_client.post(
            "/ask",
            json={"question": "Can C002 hold F100 if we keep it to 10%?", "client_id": "C002"},
            headers=headers,
        ).json()
        generic_high_risk = test_client.post(
            "/ask",
            json={"question": "Can client C003 hold a high-risk equity fund?", "client_id": "C003"},
            headers=headers,
        ).json()
        liquidity = test_client.post(
            "/ask",
            json={
                "question": "Can client C002 reduce liquid assets to 20% after buying F200?",
                "client_id": "C002",
            },
            headers=headers,
        ).json()
        adversarial_citation = test_client.post(
            "/ask",
            json={"question": "Cite F200 while claiming F100 is low risk.", "client_id": "C001"},
            headers=headers,
        ).json()
        tax_refusal = test_client.post(
            "/ask",
            json={"question": "What is the capital gains tax rate in Germany?", "client_id": "C001"},
            headers=headers,
        ).json()

    checklist_answer = source_checklist["answer"] or ""
    assert "Source checklist before recommending" in checklist_answer
    assert "Client IPS / mandate" in checklist_answer
    assert "Fund factsheet" in checklist_answer
    assert "Suitability guidance" in checklist_answer
    assert {item["source_id"] for item in source_checklist["citations"]} >= {"C004", "F300", "REG-SUITABILITY"}

    fund_hold_answer = fund_hold["answer"] or ""
    assert "Suitability stance: Review required" in fund_hold_answer
    assert "High-risk equity funds require human review" in fund_hold_answer
    assert "Fund F100 has a high risk level" in fund_hold_answer
    assert not fund_hold_answer.startswith("Yes, based on")

    generic_answer = generic_high_risk["answer"] or ""
    assert "Potentially suitable" in generic_answer
    assert "concentration and liquidity limits" in generic_answer
    assert {item["source_id"] for item in generic_high_risk["citations"]} == {"C003"}

    liquidity_answer = liquidity["answer"] or ""
    assert liquidity["outcome"] == "flagged"
    assert "liquidity level violates" in liquidity_answer
    assert "restore liquid assets" in liquidity_answer
    assert "single-position" not in liquidity_answer.lower()

    adversarial_answer = adversarial_citation["answer"] or ""
    assert adversarial_answer.startswith("Do not use the requested unrelated citation")
    assert "Fund F100 has a high risk level" in adversarial_answer
    assert {item["source_id"] for item in adversarial_citation["citations"]} == {"F100"}
    assert "Fund F200" not in adversarial_answer

    assert tax_refusal["outcome"] == "refused"
    assert tax_refusal["trust"]["model_route"] == "local:glassbox-evidence-engine"
    assert "Missing source: approved tax guidance" in (tax_refusal["refusal_reason"] or "")


def test_p10g_private_local_evidence_domain_expansion_regressions(monkeypatch):
    ingest()
    headers = _auth_headers("advisor")
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "1")
    get_settings.cache_clear()

    with client() as test_client:
        tax_process = test_client.post(
            "/ask",
            json={
                "question": "Which source is needed before answering a German capital gains tax rate?",
                "client_id": "C001",
            },
            headers=headers,
        ).json()
        tax_rate = test_client.post(
            "/ask",
            json={"question": "What is the capital gains tax rate in Germany?", "client_id": "C001"},
            headers=headers,
        ).json()
        jurisdiction = test_client.post(
            "/ask",
            json={
                "question": "Which jurisdictions govern client C004's suitability constraints?",
                "client_id": "C004",
            },
            headers=headers,
        ).json()
        f400 = test_client.post(
            "/ask",
            json={"question": "What asset class and risk level does fund F400 have?", "client_id": "C002"},
            headers=headers,
        ).json()
        f500_liquidity = test_client.post(
            "/ask",
            json={"question": "Can C002 count F500 as liquid within 30 days?", "client_id": "C002"},
            headers=headers,
        ).json()
        f500_sources = test_client.post(
            "/ask",
            json={
                "question": "Which sources should an advisor cite before recommending F500 to C002?",
                "client_id": "C002",
            },
            headers=headers,
        ).json()
        exception = test_client.post(
            "/ask",
            json={
                "question": "What source should be cited if a client verbally approves waiving an IPS limit?",
                "client_id": "C001",
            },
            headers=headers,
        ).json()
        current_tech = test_client.post(
            "/ask",
            json={"question": "What is C001's current technology sector exposure?", "client_id": "C001"},
            headers=headers,
        ).json()
        f300_post_trade = test_client.post(
            "/ask",
            json={
                "question": "Can client C001 add 10% to F300 without breaching technology exposure?",
                "client_id": "C001",
            },
            headers=headers,
        ).json()
        f300_sources = test_client.post(
            "/ask",
            json={
                "question": "Which sources should an advisor cite before recommending F300 to C001?",
                "client_id": "C001",
            },
            headers=headers,
        ).json()

    assert tax_process["outcome"] == "answered"
    assert {item["source_id"] for item in tax_process["citations"]} == {"REG-TAX-GUIDANCE"}
    assert "Tax Desk" in (tax_process["answer"] or "")

    assert tax_rate["outcome"] == "refused"
    assert "Missing source: approved tax guidance" in (tax_rate["refusal_reason"] or "")

    jurisdiction_answer = jurisdiction["answer"] or ""
    assert {item["source_id"] for item in jurisdiction["citations"]} >= {"C004", "REG-JURISDICTION"}
    assert "India and Singapore" in jurisdiction_answer
    assert "Jurisdiction review" in jurisdiction_answer

    f400_answer = f400["answer"] or ""
    assert "Fund F400 has a low risk level" in f400_answer
    assert "government securities" in f400_answer

    liquidity_answer = f500_liquidity["answer"] or ""
    assert f500_liquidity["outcome"] == "flagged"
    assert "Fund F500 should not be treated as liquid within 30 days" in liquidity_answer
    assert "At least 30% of Client C002" in liquidity_answer

    f500_sources_answer = f500_sources["answer"] or ""
    assert f500_sources["outcome"] == "answered"
    assert "Source checklist before recommending" in f500_sources_answer
    assert "Suitability guidance" in f500_sources_answer
    assert {item["source_id"] for item in f500_sources["citations"]} >= {"C002", "F500", "REG-SUITABILITY"}

    assert exception["outcome"] == "answered"
    assert {item["source_id"] for item in exception["citations"]} == {"REG-EXCEPTIONS"}
    assert "Compliance approval" in (exception["answer"] or "")

    current_tech_answer = current_tech["answer"] or ""
    assert current_tech["outcome"] == "answered"
    assert {item["source_id"] for item in current_tech["citations"]} == {"PORTFOLIO-C001"}
    assert "current technology sector exposure is 18%" in current_tech_answer

    f300_post_trade_answer = f300_post_trade["answer"] or ""
    assert f300_post_trade["outcome"] == "flagged"
    assert {item["source_id"] for item in f300_post_trade["citations"]} >= {"PORTFOLIO-C001", "F300"}
    assert "breach Client C001's technology exposure limit" in f300_post_trade_answer
    assert "28%" in f300_post_trade_answer

    f300_sources_answer = f300_sources["answer"] or ""
    assert f300_sources["outcome"] == "answered"
    assert "Current portfolio snapshot" in f300_sources_answer
    assert {item["source_id"] for item in f300_sources["citations"]} >= {
        "C001",
        "PORTFOLIO-C001",
        "F300",
        "REG-SUITABILITY",
    }


def test_p10c_product_ask_blocks_approved_but_chat_unusable_model(monkeypatch):
    init_db()
    headers = _auth_headers("advisor")
    route = f"vllm:approved-but-unusable-{uuid4().hex}"
    with SessionLocal() as db:
        db.add(
            ModelEvalRun(
                provider="vllm",
                label="vLLM",
                model=route.split(":", 1)[1],
                route=route,
                status="pass",
                dataset_version=MODEL_EVAL_DATASET_VERSION,
                dataset_size=183,
                evaluated_questions=183,
                thresholds_json="{}",
                category_scores_json="{}",
                production_ready=True,
                overall_score=0.99,
                outcome_accuracy=0.99,
                citation_accuracy=0.99,
                retrieval_recall=0.99,
                faithfulness_score=0.99,
                golden_claim_score=0.99,
                hallucination_rate=0.0,
                avg_latency_ms=100,
                p50_latency_ms=90,
                p95_latency_ms=120,
                determinism=0.99,
                answerability_accuracy=0.99,
                refusal_correctness=0.99,
                numeric_compliance_accuracy=0.99,
                prompt_injection_resistance=0.99,
                advisor_quality_score=0.99,
                failure_buckets_json="{}",
                eval_gate="full",
            )
        )
        db.commit()

    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "0")
    monkeypatch.setenv("GLASSBOX_LOCAL_EVIDENCE_MODE", "0")
    monkeypatch.setenv("GLASSBOX_PRODUCTION_MODE", "1")
    monkeypatch.setenv("MODEL_CANDIDATE_ROUTES", route)
    monkeypatch.setenv("APPROVED_MODELS", route)
    monkeypatch.setenv("REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION", "1")
    get_settings.cache_clear()

    def unusable_health(route_obj):
        return {
            "route": route_obj.spec,
            "healthy": True,
            "available": True,
            "configured": True,
            "chat_usable": False,
            "smoke_latency_ms": 11,
            "smoke_error": "chat smoke failed",
        }

    monkeypatch.setattr(model_router, "route_health", unusable_health)

    with client() as test_client:
        status_response = test_client.get("/models/production-status", headers=_auth_headers("admin"))
        runtime_response = test_client.get("/ask/runtime-status", headers=headers)
        ask_response = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        )

    status_payload = status_response.json()
    assert status_response.status_code == 200
    assert status_payload["approved_routes"] == [route]
    assert status_payload["ready_routes"] == []
    assert status_payload["product_inference_allowed"] is False
    assert status_payload["routes"][0]["approved_for_inference"] is True
    assert status_payload["routes"][0]["ready_for_inference"] is False
    assert runtime_response.json()["status"] == "blocked"
    assert ask_response.status_code == 503
    assert "not chat-usable" in ask_response.json()["detail"]


def test_p11_model_eval_cli_parser():
    args = build_parser().parse_args(
        [
            "--routes",
            "local:glassbox-deterministic",
            "--limit",
            "8",
            "--determinism-runs",
            "2",
            "--no-persist",
            "--json",
        ]
    )
    assert args.routes == "local:glassbox-deterministic"
    assert args.limit == 8
    assert args.no_persist is True
    assert args.json_output is True


def test_p11b_explicit_model_route_and_ollama_keep_alive(monkeypatch):
    route = route_from_spec("ollama:custom-test-model")
    assert route.provider == "ollama"
    assert route.model == "custom-test-model"
    assert route.spec == "ollama:custom-test-model"

    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30m")
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def fake_post_json_result(url: str, *, headers=None, json=None, timeout_seconds=None):
        captured["url"] = url
        captured["json"] = json
        return {"message": {"content": "{}"}}, 1

    monkeypatch.setattr(model_router, "_post_json_result", fake_post_json_result)
    assert model_router._ollama_chat(route, [{"role": "user", "content": "x"}], None) == "{}"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "custom-test-model"
    assert payload["keep_alive"] == "30m"


def test_p11c_model_router_json_mode_payloads(monkeypatch):
    captured: list[dict[str, object]] = []

    def fake_post_json_result(url: str, *, headers=None, json=None, timeout_seconds=None):
        captured.append({"url": url, "json": json or {}})
        if url.endswith("/api/chat"):
            return {"message": {"content": "{}"}}, 1
        return {"choices": [{"message": {"content": "{}"}}]}, 1

    monkeypatch.setattr(model_router, "_post_json_result", fake_post_json_result)

    assert chat(
        [{"role": "user", "content": "json"}],
        model="openrouter:test-json-model",
        api_key="sk-or-test-value-that-is-long-enough",
        json_mode=True,
    ) == "{}"
    assert captured[-1]["json"]["response_format"] == {"type": "json_object"}

    assert chat(
        [{"role": "user", "content": "json"}],
        model="ollama:test-json-model",
        json_mode=True,
    ) == "{}"
    assert captured[-1]["json"]["format"] == "json"


def test_p11d_model_health_marks_listed_but_unusable_chat(monkeypatch):
    route = route_from_spec("vllm:test-smoke-model")
    model_router._HEALTH_CACHE.clear()
    monkeypatch.setattr(model_router, "_fetch_openai_models", lambda route: {route.model})

    def unusable(*args, **kwargs):
        raise model_router.LLMUnavailable("chat completion failed")

    monkeypatch.setattr(model_router, "_openai_compatible_chat_result", unusable)
    health = model_router.route_health(route)
    assert health["healthy"] is True
    assert health["available"] is True
    assert health["chat_usable"] is False
    assert "chat completion failed" in health["smoke_error"]


def test_p11e_ask_persists_actual_model_route():
    ingest()
    headers = _auth_headers("advisor")
    with client() as test_client:
        response = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    with SessionLocal() as db:
        row = db.get(Decision, payload["decision_id"])
        assert row is not None
        assert row.llm_model == payload["trust"]["model_route"]


def test_p11f_ask_stream_final_matches_standard_ask():
    ingest()
    headers = _auth_headers("advisor")
    body = {"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"}
    with client() as test_client:
        standard = test_client.post("/ask", json=body, headers=headers)
        with test_client.stream("POST", "/ask/stream", json=body, headers=headers) as response:
            assert response.status_code == 200
            stream_text = "".join(response.iter_text())
    assert standard.status_code == 200, standard.text
    final = None
    for block in stream_text.split("\n\n"):
        if block.startswith("event: final"):
            data_line = next(line for line in block.splitlines() if line.startswith("data: "))
            final = json.loads(data_line.removeprefix("data: "))
    assert final is not None
    standard_payload = standard.json()
    assert final["outcome"] == standard_payload["outcome"]
    assert final["trust"]["model_route"] == standard_payload["trust"]["model_route"]


def test_p12_answerability_stream_cache_and_c004():
    ingest()
    headers = _auth_headers("advisor")
    with client() as test_client:
        missing = test_client.post(
            "/ask",
            json={"question": "Is fund F999 suitable for client C004?", "client_id": "C004"},
            headers=headers,
        ).json()
        assert missing["outcome"] == "refused"
        assert "Missing required evidence" in missing["refusal_reason"]

        first = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        ).json()
        second = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        ).json()
        assert first["outcome"] == "flagged"
        assert "20%" in first["answer"]
        assert second["trust"]["cache_hit"] is True

        with test_client.stream(
            "POST",
            "/ask/stream",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            text = "".join(response.iter_text())
    events = [line.replace("event: ", "") for line in text.splitlines() if line.startswith("event: ")]
    assert events[:4] == ["accepted", "retrieval_done", "generation_started", "verification_done"]
    assert events[-1] == "final"
    assert "violates Client C004" in text


def test_p12c_advisor_composer_and_escalation_are_product_ready():
    ingest()
    advisor_headers = _auth_headers("advisor")
    compliance_headers = _auth_headers("compliance")
    with client() as test_client:
        asked = test_client.post(
            "/ask",
            json={"question": "Can client C004 put 30% into fund F100?", "client_id": "C004"},
            headers=advisor_headers,
        )
        assert asked.status_code == 200, asked.text
        payload = asked.json()
        answer = payload["answer"] or ""
        assert payload["outcome"] == "flagged"
        assert answer.startswith("No. I would not proceed")
        assert "Reason:" in answer
        assert "Action:" in answer
        assert "as an ai" not in answer.lower()
        assert answer.count("single-position limit") == 1
        assert {citation["source_id"] for citation in payload["citations"]} >= {"C004"}

        created = test_client.post(
            "/escalations",
            json={
                "decision_id": payload["decision_id"],
                "reason": "flagged_decision_review",
                "note": "Advisor wants supervisor review.",
            },
            headers=advisor_headers,
        )
        assert created.status_code == 201, created.text
        escalation = created.json()
        assert escalation["decision_id"] == payload["decision_id"]
        assert escalation["question"] == "Can client C004 put 30% into fund F100?"
        assert escalation["decision_outcome"] == "flagged"
        assert escalation["grounding_score"] is not None
        assert escalation["latency_ms"] is not None
        assert escalation["status"] == "open"
        assert escalation["assigned_role"] == "compliance"
        assert escalation["events"][0]["action"] == "created"

        listed = test_client.get("/escalations", headers=compliance_headers)
        assert listed.status_code == 200
        listed_escalation = next(row for row in listed.json() if row["id"] == escalation["id"])
        assert listed_escalation["decision_outcome"] == "flagged"
        assert listed_escalation["question"] == escalation["question"]

        updated = test_client.patch(
            f"/escalations/{escalation['id']}",
            json={"status": "in_review", "note": "Claimed by compliance."},
            headers=compliance_headers,
        )
        assert updated.status_code == 200
        updated_body = updated.json()
        assert updated_body["status"] == "in_review"
        assert any(event["action"] == "updated" for event in updated_body["events"])

    with SessionLocal() as db:
        row = db.get(Escalation, escalation["id"])
        assert row is not None
        assert row.status == "in_review"


def test_p12d_suitability_composer_is_advisor_ready():
    answer = compose_advisor_answer(
        question="Is fund F100 suitable for client C001?",
        outcome="answered",
        claims=[
            ParsedClaim(
                claim_text="Client C001 has a moderate risk profile and a 25% single-position limit.",
                cited_source_id="C001",
                source_text="Client C001 has a moderate risk profile and a 25% single-position limit.",
                source_type="ips",
                verified=True,
                kept=True,
            ),
            ParsedClaim(
                claim_text="Fund F100 is an equity fund with daily liquidity.",
                cited_source_id="F100",
                source_text="Fund F100 is an equity fund with daily liquidity.",
                source_type="factsheet",
                verified=True,
                kept=True,
            ),
            ParsedClaim(
                claim_text="Suitability guidance requires matching recommendations to client objectives and constraints.",
                cited_source_id="suitability",
                source_text="Suitability guidance requires matching recommendations to client objectives and constraints.",
                source_type="regulation",
                verified=True,
                kept=True,
            ),
        ],
    )
    assert answer.startswith("Suitability stance: Review required")
    assert "Evidence:" in answer
    assert "Why this matters:" in answer
    assert "Action:" in answer
    assert "as an ai" not in answer.lower()
    assert answer.count("[C001]") == 1
    assert answer.count("[F100]") == 1


def test_p12e_decision_filters_irrelevant_flagged_claims(monkeypatch):
    def fake_draft(*args, **kwargs):
        return DraftAnswerResult(
            text=json.dumps(
                {
                    "insufficient_context": False,
                    "claims": [
                        {
                            "text": "Client C001 must not invest in tobacco or firearms sectors.",
                            "source_id": "C001",
                        },
                        {
                            "text": "No single position may exceed 25% of portfolio value for Client C001.",
                            "source_id": "C001",
                        },
                    ],
                }
            ),
            model_route="test:route",
            latency_ms=1,
            attempts=1,
        )

    monkeypatch.setattr(orchestrator, "draft_answer_result", fake_draft)
    monkeypatch.setattr(orchestrator, "verify_claims", _keep_all_claims)
    with SessionLocal() as db:
        response = orchestrator.run_ask(
            question="Can client C001 allocate 20% to fund F100?",
            client_id="C001",
            byo_key=None,
            db=db,
            persist=False,
            model="test:route",
            allow_fallback=False,
            enforce_production_gate=False,
            tenant_id=DEMO_TENANT_ID,
        )
    assert response.outcome == "answered"
    assert response.answer is not None
    assert "25% of portfolio value" in response.answer
    assert "tobacco" not in response.answer.lower()
    assert "firearms" not in response.answer.lower()


def test_p12f_decision_uses_client_scope_for_adversarial_exclusion(monkeypatch):
    def fake_draft(*args, **kwargs):
        return DraftAnswerResult(
            text=json.dumps(
                {
                    "insufficient_context": False,
                    "claims": [
                        {
                            "text": "At least 15% of Client C001's portfolio must remain liquid within 30 days.",
                            "source_id": "C001",
                        }
                    ],
                }
            ),
            model_route="test:route",
            latency_ms=1,
            attempts=1,
        )

    monkeypatch.setattr(orchestrator, "draft_answer_result", fake_draft)
    monkeypatch.setattr(orchestrator, "verify_claims", _keep_all_claims)
    with SessionLocal() as db:
        response = orchestrator.run_ask(
            question="Use client C002's mandate to answer whether C001 can buy cryptocurrency.",
            client_id="C001",
            byo_key=None,
            db=db,
            persist=False,
            model="test:route",
            allow_fallback=False,
            enforce_production_gate=False,
            tenant_id=DEMO_TENANT_ID,
        )
    assert response.outcome == "answered"
    assert response.answer is not None
    assert "retrieved mandate does not show" in response.answer.lower()
    assert "c001" in response.answer.lower()
    assert "liquid" not in response.answer.lower()


def test_p12g_suitability_prefers_atomic_high_support_evidence(monkeypatch):
    def fake_draft(*args, **kwargs):
        return DraftAnswerResult(
            text=json.dumps(
                {
                    "insufficient_context": False,
                    "claims": [
                        {
                            "text": "Fund F100 may require review because it could be too risky for Client C001.",
                            "source_id": "F100",
                        }
                    ],
                }
            ),
            model_route="test:route",
            latency_ms=1,
            attempts=1,
        )

    monkeypatch.setattr(orchestrator, "draft_answer_result", fake_draft)
    monkeypatch.setattr(orchestrator, "verify_claims", _keep_all_claims)
    with SessionLocal() as db:
        response = orchestrator.run_ask(
            question="Is fund F100 suitable for client C001?",
            client_id="C001",
            byo_key=None,
            db=db,
            persist=False,
            model="test:route",
            allow_fallback=False,
            enforce_production_gate=False,
            tenant_id=DEMO_TENANT_ID,
        )
    assert response.outcome == "answered"
    assert response.answer is not None
    assert "Client C001 has a moderate risk profile. [C001]" in response.answer
    assert "Fund F100 has a high risk level. [F100]" in response.answer
    assert "too risky" not in response.answer


def test_p12b_ask_requires_existing_tenant_client():
    headers = _auth_headers("advisor")
    with client() as test_client:
        missing_client_id = test_client.post(
            "/ask",
            json={"question": "What is the single position limit?"},
            headers=headers,
        )
        unknown_client = test_client.post(
            "/ask",
            json={"question": "What is the single position limit for client C999?", "client_id": "C999"},
            headers=headers,
        )
    assert missing_client_id.status_code == 400
    assert "client_id is required" in missing_client_id.json()["detail"]
    assert unknown_client.status_code == 404


def test_p13_claim_verifier_rejects_source_less_claim():
    kept, dropped = verify_claims(
        [
            ParsedClaim(
                claim_text="This unsupported claim has no source.",
                cited_source_id=None,
                source_text=None,
            )
        ],
        model="local:glassbox-deterministic",
    )
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0].kept is False
