from __future__ import annotations

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
from app.core.model_approval import MODEL_EVAL_DATASET_VERSION, route_eval_approval
from app.core.model_eval import load_eval_cases, select_eval_cases
from app.core.model_router import route_from_spec
from app.core.advisor_composer import compose_advisor_answer
from app.core.retrieval import clear_retrieval_cache
from app.main import app
from app.db import SessionLocal, engine, init_db
from app.models_db import DEMO_TENANT_ID, Escalation, ModelEvalRun
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


def test_p9_model_router_and_eval_endpoints():
    headers = _auth_headers("admin")
    with client() as test_client:
        health = test_client.get("/models/health", headers=headers)
        production_status = test_client.get("/models/production-status", headers=headers)
        dataset = test_client.get("/models/eval-dataset", headers=headers)
        approved = test_client.get("/models/approved", headers=headers)
        leaderboard = test_client.get(
            "/models/leaderboard?live=true&limit=8&determinism_runs=2&persist=false&routes=local:glassbox-deterministic",
            headers=headers,
        )
    assert health.status_code == 200
    assert {row["provider"] for row in health.json()} >= {"openrouter", "ollama", "vllm", "local"}
    assert production_status.status_code == 200
    assert "product_inference_allowed" in production_status.json()
    assert "required_eval_questions" in production_status.json()
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
                dataset_size=164,
                evaluated_questions=164,
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

    def fake_post_json(url: str, *, headers=None, json=None):
        captured["url"] = url
        captured["json"] = json
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(model_router, "_post_json", fake_post_json)
    assert model_router._ollama_chat(route, [{"role": "user", "content": "x"}], None) == "{}"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "custom-test-model"
    assert payload["keep_alive"] == "30m"


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
    assert answer.startswith("Needs review.")
    assert "Evidence:" in answer
    assert "Open checks:" in answer
    assert "Action:" in answer
    assert "as an ai" not in answer.lower()
    assert answer.count("[C001]") == 1
    assert answer.count("[F100]") == 1


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
