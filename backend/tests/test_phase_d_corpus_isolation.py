"""Phase D acceptance tests — corpus & vector isolation, /clients API.

Coverage from docs/SECURITY-IMPLEMENTATION.md, Phase D "Done when":

- Cross-tenant retrieval test: an IPS doc injected into T1 must never
  surface in T2's retrieval under any rank.
- Frontend client list comes from API; /clients endpoints work end-to-end
  with tenant scoping (advisor sees their own tenant, cross-tenant
  returns 404).
- Path-traversal guard on `source_id` (rejected at ingest and at the
  request boundary).

The retrieval-isolation test patches the in-memory chunks index for the
duration of the test to inject a "T1-only" IPS chunk, then verifies that
T2's retrieval call returns zero T1 chunks even when the query is crafted
to maximise lexical overlap.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.auth.tokens import issue_access_token
from app.core import retrieval as retrieval_mod
from app.db import SessionLocal, engine
from app.main import app
from app.models_db import DEMO_TENANT_ID, Tenant, User
from app.core.auth import service as auth_service
from corpus.ingest import (
    SHARED_TENANT_SENTINEL,
    UnsafeSourceIdError,
    assert_safe_source_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _bearer(user: User) -> dict[str, str]:
    token = issue_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


def _make_user(*, role: str, tenant_id: str = DEMO_TENANT_ID, email: str | None = None) -> User:
    email = email or f"test+phased-{uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=tenant_id,
            email=email,
            password="Phase-D-Sup3rSecur3!",
            role=role,
            email_verified=True,
        )
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user


def _make_tenant(slug_hint: str = "phased") -> Tenant:
    with SessionLocal() as db:
        tenant = Tenant(name=f"Test {slug_hint}", slug=f"t-{uuid4().hex[:6]}")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        db.expunge(tenant)
    return tenant


@pytest.fixture(autouse=True)
def _cleanup_phased_rows():
    yield
    raw = sqlite3.connect(engine.url.database)
    try:
        from tests.conftest import (
            _restore_audit_delete_guards,
            _suspend_audit_delete_guards,
        )
        _suspend_audit_delete_guards(raw)
        user_ids = [
            r[0]
            for r in raw.execute("SELECT id FROM users WHERE email LIKE 'test+phased-%'")
        ]
        if user_ids:
            ph = ",".join("?" * len(user_ids))
            raw.execute(f"DELETE FROM refresh_tokens WHERE user_id IN ({ph})", user_ids)
            raw.execute(f"DELETE FROM security_events WHERE user_id IN ({ph})", user_ids)
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
        tenant_ids = [
            r[0]
            for r in raw.execute(
                "SELECT id FROM tenants WHERE slug LIKE 't-%' AND slug != 'demo'"
            )
        ]
        for tid in tenant_ids:
            raw.execute("DELETE FROM decision_claims WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM retrieved_chunks WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM decisions WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM users WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM clients WHERE tenant_id = ?", (tid,))
            raw.execute("DELETE FROM tenants WHERE id = ?", (tid,))
        # Also clean phase-D dialog-created clients in the demo tenant so the
        # roster test doesn't accumulate junk across runs.
        raw.execute(
            "DELETE FROM clients WHERE tenant_id = ? AND client_code LIKE 'C900%'",
            (DEMO_TENANT_ID,),
        )
        raw.commit()
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Retrieval isolation — the headline Phase D acceptance check
# ---------------------------------------------------------------------------


def _seed_isolation_index(monkeypatch, t1_tenant_id: str) -> None:
    """Replace the in-memory retrieval index with three crafted chunks:
    one in T1, one in T2 (with overlapping wording), and one shared.

    The test query is constructed to be maximally similar to all three so
    pure-cosine retrieval would surface T1's chunk in T2's results — only
    the tenant filter prevents the leak.
    """
    t2_tenant_id = "00000000-0000-0000-0000-0000feedface"  # not a real tenant; used
    # only to colour the chunk. The retrieval function doesn't validate IDs.

    chunks = [
        {
            "source_id": "CT1SECRET",
            "source_type": "ips",
            "tenant_id": t1_tenant_id,
            "collection": f"glassbox_t_{t1_tenant_id}",
            "file": "corpus/tenants/t1/ips/CT1SECRET.md",
            "chunk_index": 0,
            "chunk_text": (
                "Client CT1SECRET maintains a confidential single-position "
                "limit of 17% under tenant T1's investment policy."
            ),
            "metadata": {"client_id": "CT1SECRET"},
        },
        {
            "source_id": "CT2BENIGN",
            "source_type": "ips",
            "tenant_id": t2_tenant_id,
            "collection": f"glassbox_t_{t2_tenant_id}",
            "file": "corpus/tenants/t2/ips/CT2BENIGN.md",
            "chunk_index": 0,
            "chunk_text": (
                "Client CT2BENIGN maintains a public single-position limit "
                "of 22% under tenant T2's investment policy."
            ),
            "metadata": {"client_id": "CT2BENIGN"},
        },
        {
            "source_id": "REG-SUITABILITY",
            "source_type": "regulation",
            "tenant_id": SHARED_TENANT_SENTINEL,
            "collection": "glassbox_shared",
            "file": "corpus/shared/regulations/suitability.md",
            "chunk_index": 0,
            "chunk_text": (
                "All single-position limits must be sourced from the client's "
                "IPS before recommending an allocation."
            ),
            "metadata": {"regulation_id": "REG-SUITABILITY"},
        },
    ]

    # Use deterministic hash embedding so identical strings produce identical
    # vectors across both seeding here and the live query at retrieval time.
    from app.core.embeddings import embed_texts

    vectors = embed_texts([c["chunk_text"] for c in chunks])

    monkeypatch.setattr(retrieval_mod, "_load_index", lambda: (chunks, vectors))
    # Disable the on-disk regen path so the patched index sticks.
    monkeypatch.setattr(retrieval_mod, "ensure_index", lambda: None)
    # Bust any cached lookup keyed on the prior corpus signature.
    retrieval_mod.clear_retrieval_cache()


def test_t1_chunk_never_surfaces_in_t2_retrieval(monkeypatch):
    """Inject a T1-only IPS chunk and assert that T2's retrieval never
    returns it — at any rank, with any phrasing of the query."""
    t1_tenant_id = "00000000-0000-0000-0000-0000deadbeef"
    _seed_isolation_index(monkeypatch, t1_tenant_id)

    # Query crafted to *look* like the T1 chunk so vector similarity wants to
    # rank it first. The tenant filter is the only thing standing between T2
    # and T1's data.
    query = "single-position limit under tenant T1 investment policy"

    t2_results = retrieval_mod.retrieve(
        query, client_id=None, k=10, tenant_id=DEMO_TENANT_ID
    )
    t2_source_ids = {chunk.source_id for chunk in t2_results}
    assert "CT1SECRET" not in t2_source_ids, (
        f"cross-tenant leak: T2 saw T1's chunk in results {t2_source_ids}"
    )

    # Sanity: the T1 tenant *can* see its own chunk.
    t1_results = retrieval_mod.retrieve(
        query, client_id=None, k=10, tenant_id=t1_tenant_id
    )
    t1_source_ids = {chunk.source_id for chunk in t1_results}
    assert "CT1SECRET" in t1_source_ids, (
        f"index plumbing broken: T1 didn't see its own chunk in {t1_source_ids}"
    )


def test_shared_collection_visible_to_both_tenants(monkeypatch):
    """Shared chunks (tenant_id='') must show up for *every* tenant — that's
    the whole point of the shared collection."""
    t1_tenant_id = "00000000-0000-0000-0000-0000deadbeef"
    _seed_isolation_index(monkeypatch, t1_tenant_id)

    query = "single-position limit sourced from the client's IPS"
    for caller_tenant in (DEMO_TENANT_ID, t1_tenant_id):
        results = retrieval_mod.retrieve(
            query, client_id=None, k=10, tenant_id=caller_tenant
        )
        ids = {chunk.source_id for chunk in results}
        assert "REG-SUITABILITY" in ids, (
            f"shared chunk did not surface for tenant {caller_tenant}: {ids}"
        )


def test_retrieve_with_none_tenant_falls_back_to_shared_only(monkeypatch):
    """A missing tenant context must NOT broaden to all tenants — that's a
    safe-by-default invariant. Only shared chunks should be returned."""
    t1_tenant_id = "00000000-0000-0000-0000-0000deadbeef"
    _seed_isolation_index(monkeypatch, t1_tenant_id)

    query = "single-position limit"
    results = retrieval_mod.retrieve(query, client_id=None, k=10, tenant_id=None)
    ids = {chunk.source_id for chunk in results}
    assert "CT1SECRET" not in ids
    assert "CT2BENIGN" not in ids


# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "/absolute/path",
        "C001/../C002",
        "C001\x00.md",
        "..",
        "..\\windows",
        "C001 with space",
        "C001;DROP TABLE",
    ],
)
def test_assert_safe_source_id_rejects_traversal(bad: str):
    with pytest.raises(UnsafeSourceIdError):
        assert_safe_source_id(bad)


@pytest.mark.parametrize("good", ["C001", "F100", "REG-SUITABILITY", "C_004", "abc.def"])
def test_assert_safe_source_id_accepts_safe_ids(good: str):
    assert assert_safe_source_id(good) == good


def test_ask_endpoint_rejects_traversal_client_id(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.post(
        "/ask",
        headers=_bearer(user),
        json={"question": "anything", "client_id": "../etc/passwd"},
    )
    # Pydantic 422 on validator failure — the request never reaches retrieval.
    assert res.status_code == 422, res.text


# ---------------------------------------------------------------------------
# /clients API: list, create, tenant scope, 404-not-403 on cross-tenant
# ---------------------------------------------------------------------------


def test_demo_seed_clients_visible_via_api(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.get("/clients", headers=_bearer(user))
    assert res.status_code == 200, res.text
    codes = {row["client_code"] for row in res.json()}
    # The Phase A migration / dev-seed populates C001..C004 under demo.
    assert {"C001", "C002", "C003", "C004"}.issubset(codes), codes


def test_create_client_persists_under_callers_tenant(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    payload = {
        "client_code": "C9001",
        "display_name": "Phase D Test Client",
        "household": "Test Household",
        "risk_profile": "moderate",
        "jurisdictions": ["CH", "US"],
        "max_single_position_pct": 18,
        "min_liquid_within_30d_pct": 22,
        "excluded_sectors": ["tobacco"],
        "excluded_regions": ["russia"],
        "ips_version": "v1.0",
        "ips_updated_at": "2026-05-23",
        "aum_eur": 5_000_000,
        "advisor_name": "Phase D Tester",
    }
    res = client.post("/clients", headers=_bearer(user), json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["client_code"] == "C9001"
    assert body["display_name"] == "Phase D Test Client"
    assert body["jurisdictions"] == ["CH", "US"]

    # And it shows up in the listing.
    listing = client.get("/clients", headers=_bearer(user)).json()
    assert "C9001" in {row["client_code"] for row in listing}


def test_clients_list_is_tenant_scoped(client, no_auth_override):
    t2 = _make_tenant("clients")
    advisor_demo = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    advisor_t2 = _make_user(role="advisor", tenant_id=t2.id)

    # Demo tenant has the four seed clients. T2 starts empty.
    demo_codes = {
        row["client_code"]
        for row in client.get("/clients", headers=_bearer(advisor_demo)).json()
    }
    t2_codes = {
        row["client_code"]
        for row in client.get("/clients", headers=_bearer(advisor_t2)).json()
    }
    assert {"C001", "C002", "C003", "C004"}.issubset(demo_codes)
    assert t2_codes == set(), f"T2 should not see demo clients; got {t2_codes}"


def test_get_other_tenants_client_returns_404_not_403(client, no_auth_override):
    t2 = _make_tenant("scope")
    advisor_t2 = _make_user(role="advisor", tenant_id=t2.id)

    # C001 exists, but only under the demo tenant. T2 must get 404.
    res = client.get("/clients/C001", headers=_bearer(advisor_t2))
    assert res.status_code == 404


def test_create_client_rejects_invalid_code(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    res = client.post(
        "/clients",
        headers=_bearer(user),
        json={
            "client_code": "../etc/passwd",
            "display_name": "x",
            "risk_profile": "moderate",
        },
    )
    assert res.status_code == 422, res.text


def test_create_client_409_on_duplicate_within_same_tenant(client, no_auth_override):
    user = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    payload = {
        "client_code": "C9002",
        "display_name": "Phase D Dupe",
        "risk_profile": "moderate",
    }
    first = client.post("/clients", headers=_bearer(user), json=payload)
    assert first.status_code == 201
    second = client.post("/clients", headers=_bearer(user), json=payload)
    assert second.status_code == 409


def test_two_tenants_may_reuse_the_same_client_code(client, no_auth_override):
    t2 = _make_tenant("dupcode")
    user_demo = _make_user(role="advisor", tenant_id=DEMO_TENANT_ID)
    user_t2 = _make_user(role="advisor", tenant_id=t2.id)
    payload = {
        "client_code": "C9003",
        "display_name": "Reused Code",
        "risk_profile": "moderate",
    }
    assert client.post("/clients", headers=_bearer(user_demo), json=payload).status_code == 201
    # Same code in T2 is fine: the uniqueness constraint is per-tenant.
    res = client.post("/clients", headers=_bearer(user_t2), json=payload)
    assert res.status_code == 201, res.text


def test_clients_endpoints_require_auth(client, no_auth_override):
    for method, path in [("GET", "/clients"), ("POST", "/clients"), ("GET", "/clients/C001")]:
        res = client.request(method, path, json={"client_code": "X1", "display_name": "x", "risk_profile": "moderate"})
        assert res.status_code == 401, f"{method} {path} should 401 unauth"
