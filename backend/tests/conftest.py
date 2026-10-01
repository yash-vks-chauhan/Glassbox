"""Shared test fixtures.

The Phase C auth guards (`current_user`, `require_role`) reject any request
without a valid bearer token. The bulk of the existing acceptance suite
hits business endpoints without minting JWTs, and rewriting every call site
to login first would obscure what those tests actually verify (the
LLM/retrieval/audit pipeline, not auth).

So we install a *test-only* dependency override that returns a default
"demo admin" user. The override is on by default; Phase C's own isolation
tests pop it off via the `no_auth_override` fixture to exercise the real
401/403 paths.

The whole suite runs against a throwaway state directory (SQLite DB, vector
store, dev mail dir) and never reads the developer's `.env`, so a test run
can't write into `backend/glassbox_local.db`, send real email through a
configured SMTP server, or call a hosted model with a real API key.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

# ---------------------------------------------------------------------------
# Hermetic environment. This must run before anything imports `app`: app.db
# builds its engine from the settings at import time. Some tests also import
# helpers via `tests.conftest`, which executes this module a second time, so
# the state dir is shared through an env var instead of re-created.
# ---------------------------------------------------------------------------
_TEST_STATE_DIR = Path(
    os.environ.get("GLASSBOX_TEST_STATE_DIR") or tempfile.mkdtemp(prefix="glassbox-tests-")
)
os.environ["GLASSBOX_TEST_STATE_DIR"] = str(_TEST_STATE_DIR)

# Opt-in Postgres run (CI does this): point GLASSBOX_TEST_DATABASE_URL at an
# *empty* database whose name contains "test". The name check stops a stray
# shell variable from aiming the suite at a real database.
_TEST_DATABASE_URL = os.environ.get("GLASSBOX_TEST_DATABASE_URL", "").strip()
if _TEST_DATABASE_URL:
    _database_name = _TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in _database_name:
        raise RuntimeError(
            "GLASSBOX_TEST_DATABASE_URL must name a throwaway database containing "
            f"'test' (got {_database_name!r})."
        )
else:
    _TEST_DATABASE_URL = f"sqlite:///{_TEST_STATE_DIR / 'glassbox_test.db'}"

os.environ.update(
    {
        "DATABASE_URL": _TEST_DATABASE_URL,
        "CHROMA_DIR": str(_TEST_STATE_DIR / "chroma_store"),
        "DEV_MAIL_DIR": str(_TEST_STATE_DIR / "mail"),
        "GLASSBOX_EMBEDDING_BACKEND": "hash",
        "GLASSBOX_LOCAL_LLM": "1",
        "GLASSBOX_LOCAL_EVIDENCE_MODE": "1",
        "GLASSBOX_PRODUCTION_MODE": "0",
    }
)
for _credential in (
    "OPENROUTER_API_KEY",
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "BOOTSTRAP_SETUP_KEY",
):
    os.environ.pop(_credential, None)

from app import config as _app_config  # noqa: E402

# Ignore the developer's .env / .env.local so local runs match CI.
_app_config.Settings.model_config["env_file"] = None
_app_config.get_settings.cache_clear()

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.auth import service as auth_service  # noqa: E402
from app.core.auth.deps import current_user  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models_db import DEMO_TENANT_ID, User  # noqa: E402
from corpus.ingest import ingest  # noqa: E402


def _migrate_to_head() -> None:
    """Build the schema with the real migration chain, the same path a
    Postgres deployment takes, so a broken migration fails the suite."""
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def hermetic_state():
    """Migrate the throwaway database and build the vector index once, then
    delete the whole state directory when the session ends."""
    _migrate_to_head()
    init_db()
    ingest()
    yield _TEST_STATE_DIR
    engine.dispose()
    shutil.rmtree(_TEST_STATE_DIR, ignore_errors=True)


# Reuse one demo-admin row across the whole session so tests don't pile up
# fake users. The prefix `system+` keeps this row outside the `test+%` glob
# that Phase B's per-test cleanup uses, so it survives across tests.
_TEST_USER_EMAIL = "system+conftest-default@example.com"
_TEST_USER_PASSWORD = "Conftest-Sup3rSecur3!"
_PATCHED_DEPENDANTS: list[tuple[object, object]] = []


def _ensure_default_user() -> str:
    """Return the user_id of the persistent demo-admin test user, creating
    it on first call. Idempotent across pytest invocations."""
    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(
                User.tenant_id == DEMO_TENANT_ID,
                User.email == _TEST_USER_EMAIL,
            )
        )
        if existing is not None:
            return existing.id
        user = auth_service.create_user(
            db,
            tenant_id=DEMO_TENANT_ID,
            email=_TEST_USER_EMAIL,
            password=_TEST_USER_PASSWORD,
            role="admin",  # broad enough to satisfy every require_role gate
            display_name="Test Default Admin",
            email_verified=True,
        )
        db.commit()
        return user.id


@pytest.fixture(scope="session")
def default_user_id(hermetic_state) -> str:
    return _ensure_default_user()


def _override_with(user_id: str):
    """Replace `current_user` (and downstream `require_role(...)` closures)
    with a function that loads the persistent demo-admin user from the
    request's db session. Mutations made by the router (e.g. MFA enrollment)
    persist because the user is attached to the same session.

    Tests that need the *real* JWT path (Phase B's MFA / invite tests, Phase
    C's isolation tests) declare the `no_auth_override` fixture to opt out."""
    from fastapi import Depends
    from app.db import get_db

    def _impl(request=None, db=Depends(get_db)) -> User:
        user = db.get(User, user_id)
        assert user is not None, "test user disappeared mid-test"
        return user

    app.dependency_overrides[current_user] = _impl
    # Every call to require_role() returns a *new* function object, so
    # overriding by reference doesn't catch them. Instead, monkey-patch
    # the require_role factory itself so future calls also produce the
    # override. We do this via dependency_overrides[require_role]: FastAPI
    # respects overrides on callable factories at resolve time.
    #
    # require_role isn't itself a dependency though — what FastAPI sees is
    # the *returned* closure. We have to override every closure currently
    # registered. Walk app.routes and rebind any route whose dependant
    # ultimately resolves require_role to our impl.
    _override_role_deps(_impl)


def _override_role_deps(impl) -> None:
    from app.core.auth import deps as auth_deps

    # Cleaner: replace require_role with a version that returns `impl`.
    # Only affects test runs because we restore in the fixture teardown.
    auth_deps._original_require_role = getattr(  # type: ignore[attr-defined]
        auth_deps, "_original_require_role", auth_deps.require_role
    )

    def _patched(*roles: str):
        return impl

    # Reach into every route's existing dep on require_role and swap it.
    for route in app.routes:
        deps = getattr(route, "dependant", None)
        if deps is None:
            continue
        _swap_in_dependant(deps, impl)

    auth_deps.require_role = _patched  # type: ignore[assignment]


def _swap_in_dependant(dep, impl) -> None:
    for sub in list(dep.dependencies):
        call = sub.call
        if call is None:
            continue
        # require_role's closure has __qualname__ "require_role.<locals>._checker"
        qname = getattr(call, "__qualname__", "")
        if qname.endswith(".require_role.<locals>._checker"):
            _PATCHED_DEPENDANTS.append((sub, call))
            sub.call = impl
        if call is current_user:
            _PATCHED_DEPENDANTS.append((sub, call))
            sub.call = impl
        _swap_in_dependant(sub, impl)


def _clear_overrides() -> None:
    from app.core.auth import deps as auth_deps

    app.dependency_overrides.pop(current_user, None)
    if hasattr(auth_deps, "_original_require_role"):
        auth_deps.require_role = auth_deps._original_require_role  # type: ignore[assignment]
    while _PATCHED_DEPENDANTS:
        dependant, original_call = _PATCHED_DEPENDANTS.pop()
        setattr(dependant, "call", original_call)


@pytest.fixture(autouse=True)
def auth_override(default_user_id):
    """Default: every test sees the demo admin user. Tests that want the
    real auth path declare `no_auth_override` which runs *before* this
    fixture and sets a flag we honor."""
    if os.environ.get("GLASSBOX_NO_AUTH_OVERRIDE") == "1":
        yield
        return
    _override_with(default_user_id)
    yield
    _clear_overrides()


@pytest.fixture()
def no_auth_override(monkeypatch):
    """Opt-in for Phase C isolation tests that want the real 401/403 paths."""
    monkeypatch.setenv("GLASSBOX_NO_AUTH_OVERRIDE", "1")
    # Make sure no leftover override from an earlier autouse run lingers.
    _clear_overrides()
    yield
    _clear_overrides()


# ---------------------------------------------------------------------------
# Helpers for tests that need to mint extra users / log in for real
# ---------------------------------------------------------------------------


def make_user(
    *,
    role: str = "advisor",
    tenant_id: str = DEMO_TENANT_ID,
    password: str = "Sup3rSecur3-Pass!",
    email: str | None = None,
) -> str:
    """Create a user and return their id. Caller cleans up via the email
    prefix `test+` (see _wipe convention)."""
    email = email or f"test+{uuid4().hex[:10]}@example.com"
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=tenant_id,
            email=email,
            password=password,
            role=role,
            display_name="Phase C Test",
            email_verified=True,
        )
        db.commit()
        return user.id


def make_tenant(slug: str | None = None) -> str:
    """Create a second tenant for cross-tenant isolation tests."""
    from app.models_db import Tenant

    slug = slug or f"t-{uuid4().hex[:6]}"
    with SessionLocal() as db:
        tenant = Tenant(name=f"Tenant {slug}", slug=slug)
        db.add(tenant)
        db.commit()
        return tenant.id


def login_for_token(client, *, email: str, password: str, tenant_slug: str) -> str:
    res = client.post(
        "/auth/login",
        json={"email": email, "password": password, "tenant_slug": tenant_slug},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


