"""Phase C acceptance tests — authorization & tenant isolation.

Coverage from docs/SECURITY-IMPLEMENTATION.md, Phase C "Done when":

- Every protected endpoint returns 401 without a token.
- Cross-tenant audit returns **404, not 403** (never leak existence).
- Advisor sees only their own decisions; compliance / admin see every
  decision in their tenant.
- Advisor blocked from /models/* and /determinism with 403.
- /auth/me returns the bearer's user, not the conftest demo user.

These tests use the `no_auth_override` fixture so the real JWT-decoding
path runs end-to-end.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.db import SessionLocal, engine
from app.main import app
from app.models_db import DEMO_TENANT_ID, ClientRecord, Decision, Tenant, User


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _bearer(user: User) -> dict[str, str]:
    token = issue_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role
    )
    return {"Authorization": f"Bearer {token}"}


def _make_user(*, role: str, tenant_id: str = DEMO_TENANT_ID, email: str | None = None) -> User:
    email = email or f"test+phasec-{uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=tenant_id,
            email=email,
            password="Phase-C-Sup3rSecur3!",
            role=role,
            email_verified=True,
        )
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user


def _make_tenant(slug_hint: str = "t") -> Tenant:
    with SessionLocal() as db:
        tenant = Tenant(name=f"Test {slug_hint}", slug=f"t-{uuid4().hex[:6]}")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        db.expunge(tenant)
    return tenant


def _make_client(*, tenant_id: str, code: str = "C901") -> None:
    with SessionLocal() as db:
        if db.scalar(
            select(ClientRecord).where(
                ClientRecord.tenant_id == tenant_id,
                ClientRecord.client_code == code,
            )
        ):
            return
        db.add(
            ClientRecord(
                tenant_id=tenant_id,
                client_code=code,
                display_name=f"Test Client {code}",
                household="Test",
                risk_profile="moderate",
                jurisdictions=["US"],
                max_single_position_pct=20,
                min_liquid_within_30d_pct=10,
                excluded_sectors=[],
                excluded_regions=[],
            )
        )
        db.commit()


@pytest.fixture(autouse=True)
def _cleanup_phasec_rows():
    yield
    raw = sqlite3.connect(engine.url.database)
    try:
        # Phase E audit DELETE guards block these cleanup deletes by design.
        # Suspend them just for the test-fixture cleanup window.
        from tests.conftest import (
            _restore_audit_delete_guards,
            _suspend_audit_delete_guards,
        )
        _suspend_audit_delete_guards(raw)
        user_ids = [
            r[0]
            for r in raw.execute("SELECT id FROM users WHERE email LIKE 'test+phasec-%'")
        ]
        if user_ids:
            ph = ",".join("?" * len(user_ids))
            raw.execute(f"DELETE FROM refresh_tokens WHERE user_id IN ({ph})", user_ids)
            raw.execute(f"DELETE FROM security_events WHERE user_id IN ({ph})", user_ids)
            raw.execute(
                f"DELETE FROM escalation_events WHERE escalation_id IN "
                f"(SELECT id FROM escalations WHERE created_by_user_id IN ({ph}))",
                user_ids,
            )
            raw.execute(f"DELETE FROM escalations WHERE created_by_user_id IN ({ph})", user_ids)
            raw.execute(
                f"DELETE FROM decision_claims WHERE decision_id IN "
                f"(SELECT id FROM decisions WHERE user_id IN ({ph}))",
                user_ids,
            )
            raw.execute(
                f"DELETE FROM retrieved_chunks WHERE decision_id IN "
                f"(SELECT id FROM decisions WHERE user_id IN ({ph}))",
                user_ids,
            )
            raw.execute(f"DELETE FROM decisions WHERE user_id IN ({ph})", user_ids)
            raw.execute(f"DELETE FROM users WHERE id IN ({ph})", user_ids)
        # And the tenants we made.
        tenant_ids = [
            r[0]
            for r in raw.execute(
                "SELECT id FROM tenants WHERE slug LIKE 't-%' AND slug != 'demo'"
            )
        ]
        for tid in tenant_ids:
            raw.execute("DELETE FROM decision_claims WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM escalation_events WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM escalations WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM retrieved_chunks WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM decisions WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM users WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM clients WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM tenants WHERE id = ?", (tid,))
        raw.commit()
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Unauth → 401 on every protected endpoint
# ---------------------------------------------------------------------------


PROTECTED_ENDPOINTS = [
    ("POST", "/ask", {"question": "anything"}),
    ("GET", "/audit", None),
    ("GET", "/audit/some-id", None),
    ("GET", "/escalations", None),
    ("POST", "/escalations", {"decision_id": "some-id", "reason": "review"}),
    ("GET", "/metrics/summary", None),
    ("POST", "/determinism", {"question": "anything"}),
    ("GET", "/models/health", None),
    ("GET", "/models/leaderboard", None),
    ("GET", "/models/eval-runs", None),
    ("GET", "/models/eval-dataset", None),
    ("GET", "/models/approved", None),
    ("GET", "/llm/status", None),
    ("GET", "/auth/me", None),
    ("POST", "/auth/invite", {"email": "a@b.com", "role": "advisor"}),
    ("POST", "/auth/mfa/enroll", None),
    ("POST", "/auth/mfa/verify", {"code": "123456"}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED_ENDPOINTS)
def test_unauthenticated_request_returns_401(
    client, no_auth_override, method, path, body
):
    res = client.request(method, path, json=body)
    assert res.status_code == 401, f"{method} {path} should 401 unauth"


# ---------------------------------------------------------------------------
# /auth/me returns the bearer's user
# ---------------------------------------------------------------------------


def test_auth_me_returns_authenticated_user(client, no_auth_override):
    user = _make_user(role="advisor")
    res = client.get("/auth/me", headers=_bearer(user))
    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == user.id
    assert body["email"] == user.email
    assert body["role"] == "advisor"
    assert body["tenant_id"] == DEMO_TENANT_ID
    assert body["tenant_slug"] == "demo"


# ---------------------------------------------------------------------------
# Cross-tenant isolation: 404 on /audit/{id}, never 403
# ---------------------------------------------------------------------------


def test_cross_tenant_audit_returns_404_not_403(client, no_auth_override):
    # Two tenants, two users.
    t2 = _make_tenant("rival")
    u1 = _make_user(role="admin", tenant_id=DEMO_TENANT_ID)
    u2 = _make_user(role="admin", tenant_id=t2.id)

    # U1 asks a question -> a decision is recorded in DEMO tenant.
    ask = client.post(
        "/ask",
        headers=_bearer(u1),
        json={"question": "Can client C001 hold 30% in one position?", "client_id": "C001"},
    )
    assert ask.status_code == 200, ask.text
    decision_id = ask.json()["decision_id"]

    # U2 (different tenant, valid admin token) cannot read U1's decision.
    cross = client.get(f"/audit/{decision_id}", headers=_bearer(u2))
    assert cross.status_code == 404, (
        f"cross-tenant read must be 404 (not 403); got {cross.status_code}"
    )

    # Sanity: U1 can read it.
    same = client.get(f"/audit/{decision_id}", headers=_bearer(u1))
    assert same.status_code == 200


def test_cross_tenant_audit_list_does_not_leak_other_tenants_rows(
    client, no_auth_override
):
    t2 = _make_tenant("rival2")
    u1 = _make_user(role="admin", tenant_id=DEMO_TENANT_ID)
    u2 = _make_user(role="admin", tenant_id=t2.id)

    # U1 creates a decision in DEMO.
    ask1 = client.post(
        "/ask",
        headers=_bearer(u1),
        json={"question": "what is C001 max single position?", "client_id": "C001"},
    )
    assert ask1.status_code == 200
    u1_decision_id = ask1.json()["decision_id"]

    # U2's audit list must not include U1's decision_id.
    listing = client.get("/audit?limit=200", headers=_bearer(u2))
    assert listing.status_code == 200
    ids = {row["id"] for row in listing.json()}
    assert u1_decision_id not in ids


# ---------------------------------------------------------------------------
# Within-tenant: advisor sees own only, compliance sees all
# ---------------------------------------------------------------------------


def test_advisor_sees_only_own_decisions_within_tenant(client, no_auth_override):
    advisor_a = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    advisor_b = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)

    # A asks.
    res_a = client.post(
        "/ask",
        headers=_bearer(advisor_a),
        json={"question": "C001 single position limit", "client_id": "C001"},
    )
    assert res_a.status_code == 200
    a_decision = res_a.json()["decision_id"]

    # B's audit list must not include A's decision.
    listing = client.get("/audit?limit=200", headers=_bearer(advisor_b))
    assert listing.status_code == 200
    assert a_decision not in {row["id"] for row in listing.json()}

    # B's direct fetch on A's decision is 404 (same-tenant, but other advisor).
    direct = client.get(f"/audit/{a_decision}", headers=_bearer(advisor_b))
    assert direct.status_code == 404


def test_compliance_sees_other_advisors_decisions_in_same_tenant(
    client, no_auth_override
):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    compliance = _make_user(role="compliance", tenant_id=DEMO_TENANT_ID)

    res = client.post(
        "/ask",
        headers=_bearer(advisor),
        json={"question": "C001 single position limit", "client_id": "C001"},
    )
    assert res.status_code == 200
    advisor_decision = res.json()["decision_id"]

    # Compliance can read the advisor's decision.
    direct = client.get(f"/audit/{advisor_decision}", headers=_bearer(compliance))
    assert direct.status_code == 200

    # And it's in the listing.
    listing = client.get("/audit?limit=200", headers=_bearer(compliance))
    assert listing.status_code == 200
    assert advisor_decision in {row["id"] for row in listing.json()}


# ---------------------------------------------------------------------------
# Role gates
# ---------------------------------------------------------------------------


def test_advisor_is_forbidden_from_models_endpoints(client, no_auth_override):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    for path in (
        "/models/health",
        "/models/leaderboard",
        "/models/eval-runs",
        "/models/eval-dataset",
        "/models/approved",
        "/llm/status",
    ):
        res = client.get(path, headers=_bearer(advisor))
        assert res.status_code == 403, f"{path} should 403 for advisor; got {res.status_code}"


def test_advisor_is_forbidden_from_determinism(client, no_auth_override):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.post(
        "/determinism",
        headers=_bearer(advisor),
        json={"question": "anything"},
    )
    assert res.status_code == 403


def test_advisor_is_forbidden_from_invite(client, no_auth_override):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.post(
        "/auth/invite",
        headers=_bearer(advisor),
        json={"email": "test+phasec-invitee@example.com", "role": "advisor"},
    )
    assert res.status_code == 403


def test_admin_can_access_models_health(client, no_auth_override):
    admin = _make_user(role="admin", tenant_id=DEMO_TENANT_ID)
    res = client.get("/models/health", headers=_bearer(admin))
    assert res.status_code == 200


def test_escalation_assignment_is_tenant_scoped_and_reviewer_only(client, no_auth_override):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    reviewer = _make_user(role="compliance", tenant_id=DEMO_TENANT_ID)
    same_tenant_advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    t2 = _make_tenant("esc-assign")
    other_tenant_reviewer = _make_user(role="compliance", tenant_id=t2.id)

    asked = client.post(
        "/ask",
        headers=_bearer(advisor),
        json={"question": "Can client C001 hold 30% in one position?", "client_id": "C001"},
    )
    assert asked.status_code == 200, asked.text
    created = client.post(
        "/escalations",
        headers=_bearer(advisor),
        json={"decision_id": asked.json()["decision_id"], "reason": "review"},
    )
    assert created.status_code == 201, created.text
    escalation_id = created.json()["id"]

    advisor_assignee = client.patch(
        f"/escalations/{escalation_id}",
        headers=_bearer(reviewer),
        json={"assigned_to_user_id": same_tenant_advisor.id},
    )
    assert advisor_assignee.status_code == 422

    cross_tenant_assignee = client.patch(
        f"/escalations/{escalation_id}",
        headers=_bearer(reviewer),
        json={"assigned_to_user_id": other_tenant_reviewer.id},
    )
    assert cross_tenant_assignee.status_code == 404

    valid_assignee = client.patch(
        f"/escalations/{escalation_id}",
        headers=_bearer(reviewer),
        json={"assigned_to_user_id": reviewer.id, "status": "in_review"},
    )
    assert valid_assignee.status_code == 200
    body = valid_assignee.json()
    assert body["assigned_to_user_id"] == reviewer.id
    assert body["status"] == "in_review"


# ---------------------------------------------------------------------------
# Tenant scoping on /ask: the recorded decision is tagged with caller's tenant
# ---------------------------------------------------------------------------


def test_ask_records_tenant_and_user_on_decision(client, no_auth_override):
    t2 = _make_tenant("ask")
    _make_client(tenant_id=t2.id, code="C901")
    u2 = _make_user(role="advisor", tenant_id=t2.id)

    res = client.post(
        "/ask",
        headers=_bearer(u2),
        json={"question": "What is the single position limit for client C901?", "client_id": "C901"},
    )
    assert res.status_code == 200
    decision_id = res.json()["decision_id"]

    with SessionLocal() as db:
        row = db.scalar(select(Decision).where(Decision.id == decision_id))
        assert row is not None
        assert row.tenant_id == t2.id
        assert row.user_id == u2.id


# ---------------------------------------------------------------------------
# Tenant scoping on /metrics/summary
# ---------------------------------------------------------------------------


def test_metrics_summary_forbidden_for_advisor(client, no_auth_override):
    advisor = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.get("/metrics/summary", headers=_bearer(advisor))
    assert res.status_code == 403


def test_metrics_summary_is_tenant_scoped(client, no_auth_override):
    t2 = _make_tenant("metrics")
    u_demo = _make_user(role="compliance", tenant_id=DEMO_TENANT_ID)
    u_t2 = _make_user(role="compliance", tenant_id=t2.id)

    # Generate exactly one decision in t2.
    advisor_t2 = _make_user(role="advisor", tenant_id=t2.id)
    _make_client(tenant_id=t2.id, code="C902")
    client.post(
        "/ask",
        headers=_bearer(advisor_t2),
        json={"question": "What is the single position limit for client C902?", "client_id": "C902"},
    )

    demo_metrics = client.get("/metrics/summary", headers=_bearer(u_demo)).json()
    t2_metrics = client.get("/metrics/summary", headers=_bearer(u_t2)).json()

    assert t2_metrics["total"] == 1
    # The demo tenant already has hundreds of backfilled decisions from Phase A.
    assert demo_metrics["total"] >= 1
    assert demo_metrics["total"] != t2_metrics["total"]


# ---------------------------------------------------------------------------
# Stale token: user moved tenants (or deleted) -> 401
# ---------------------------------------------------------------------------


def test_token_whose_user_no_longer_exists_is_401(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    headers = _bearer(user)

    # Delete the user out from under the token.
    with SessionLocal() as db:
        u = db.get(User, user.id)
        db.delete(u)
        db.commit()

    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 401
