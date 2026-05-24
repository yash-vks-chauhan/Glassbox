# GlassBox — Auth & Security Implementation

> Plan of record for turning GlassBox from a single-user local demo into a **multi-tenant, production-hardened, locally-deployed** product. Cloud deploy is a separate, later pass.
>
> Read this together with [README.md](../README.md) and [BUILD-SPEC.md](../BUILD-SPEC.md). Each phase here is a checkpoint with a clear definition of done; do not start phase N+1 until phase N's acceptance test is green.

---

## 0. Identity model (the contract everything else respects)

Three nested entities:

```
Tenant (a firm — e.g. "Müller Wealth GmbH")
  └─ User (an employee — advisor / compliance / admin / owner)
       └─ acts on Clients (the firm's HNW clients — C001, C002, ...)
```

- **No self-signup.** A tenant is created by us (or via a "request access" form). The first user is `owner`; the owner invites everyone else.
- **Roles:** `owner` > `admin` > `compliance` > `advisor`.
- **Hard rule (the firewall):** no row crosses a tenant boundary. Ever. Enforced by a FastAPI dependency, not developer discipline.
- **404, not 403** on cross-tenant access — never leak existence.

---

## Phase A — Data foundation

**Goal:** schema is ready to hold tenants, users, sessions, clients, and tenant-scoped audit data. No auth code yet.

**Build:**
- New tables: `tenants`, `users`, `user_invitations`, `refresh_tokens`, `password_resets`, `clients`, `byo_keys`, `security_events`.
- Add `tenant_id` (NOT NULL FK) to `decisions`, `decision_claims`, `retrieved_chunks`, `model_eval_runs`, `model_eval_results`. Add `user_id` (nullable FK) to `decisions`.
- DB constraints: unique `(tenant_id, email)` on users, unique `(tenant_id, client_code)` on clients, indexes on every `tenant_id`.
- Alembic migration creates the schema, seeds a `demo` tenant, backfills existing rows under it.

**Done when:**
- `alembic upgrade head` succeeds on a fresh and an existing local DB.
- `pytest backend/tests/test_phase_a_schema.py` passes (schema exists, demo tenant exists, every legacy decision row is tenant-scoped).
- All existing acceptance tests still pass.

---

## Phase B — Authentication

**Goal:** users can sign in, refresh, log out, reset password, and enroll MFA — locally.

**Build:**
- Password hashing with **Argon2id** (`argon2-cffi`), tuned to ~250 ms.
- JWT access token (15 min, HS256, claims: `sub`, `tid`, `role`, `kid`, `exp`, `iat`, `jti`).
- Refresh token: 256-bit opaque, stored hashed, **rotated on every use**. Detect reuse → revoke the entire family (token-theft signal).
- HttpOnly + Secure + SameSite=Lax refresh cookie, scoped to `/auth/refresh`.
- Endpoints (`backend/app/routers/auth.py`):
  - `POST /auth/login`, `/auth/refresh`, `/auth/logout`
  - `POST /auth/invite` (admin), `POST /auth/accept-invite`
  - `POST /auth/forgot`, `POST /auth/reset`
  - `POST /auth/mfa/enroll`, `POST /auth/mfa/verify`
  - `GET /auth/me`
- Brute-force defense: lock account after 5 failed logins in 15 min; per-email AND per-IP counters.
- MFA (TOTP via `pyotp`); recovery codes shown once on enroll; **required** for `admin`/`owner`.
- Email: local dev writes `.eml` files to `/tmp/glassbox-mail/`. `EmailService.send(...)` interface so SES/Postmark drops in later.

**Done when:**
- `pytest backend/tests/test_phase_b_auth.py` passes: full login → refresh → logout flow; lockout triggers; MFA happy + sad path; reset and invite flows complete.
- Failed-login responses are indistinguishable from unknown-user responses (no enumeration).

---

## Phase C — Authorization & tenant scoping

**Goal:** every endpoint requires auth and filters by `tenant_id`.

**Build:**
- `current_user` dependency (validates JWT, loads `User`).
- `require_role(*roles)` guard.
- All routers updated:
  - `POST /ask`: advisor+; writes `user_id` and `tenant_id`.
  - `GET /audit`, `GET /audit/{id}`: tenant-scoped; advisor sees own only; compliance/admin see all in tenant.
  - `GET /metrics/summary`: tenant-scoped; compliance+.
  - `/models/*`: admin/owner only.
  - `/determinism`: compliance+.
  - `/clients/*` (new in Phase D): tenant-scoped CRUD.

**Done when:**
- `pytest backend/tests/test_phase_c_isolation.py` passes the *tenant-isolation test*: user U1 in tenant T1 calls `/ask`, captures `decision_id`; user U2 in tenant T2 gets **404** (not 403) on `GET /audit/{that_id}`.
- All previously open endpoints return 401 without a token.

---

## Phase D — Data isolation: corpus & vectors

**Goal:** one tenant's IPS can never surface in another tenant's retrieval.

**Build:**
- Chroma collection per tenant: `glassbox_t_{tenant_id}`. Shared content (regulations, public factsheets) goes in `glassbox_shared`. Retrieval unions both.
- Corpus filesystem layout:
  ```
  backend/corpus/
    shared/{regulations,factsheets}/
    tenants/{tenant_id}/ips/
  ```
- Path-traversal guard: reject any `source_id` containing `..` or absolute paths.
- Move clients off `localStorage` ([frontend/lib/clients.ts](../frontend/lib/clients.ts)) and into `GET /clients` / `POST /clients`. C001–C004 become tenant `demo`'s seed clients.

**Done when:**
- Cross-tenant retrieval test: inject IPS doc into T1; query as T2; assert T1's content is not in the retrieved chunks under any rank.
- Frontend client list comes from API; localStorage path removed.

---

## Phase E — Production hardening

**Goal:** sealed CORS, security headers, secrets, persistent rate limiting, encrypted BYO keys, **tamper-evident audit log**.

**Build:**
- **CORS:** explicit origin from `FRONTEND_ORIGIN`; `allow_credentials=True`; method allowlist. Replaces the wildcard in [backend/app/main.py](../backend/app/main.py).
- **Security headers** middleware: HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, minimal CSP.
- **Persistent rate limit:** SQLite/Redis sliding window keyed on `(user_id || ip, route_class)`. Tiers: `/auth/*` strict (10/min), `/ask` 60/min/user, public reads loose. Returns `Retry-After`.
- **Secrets:** `JWT_SIGNING_KEY`, `APP_ENCRYPTION_KEY` (32B for AES-GCM), `COOKIE_SECRET` generated by `scripts/init_secrets.py`. Loaded from env. JWT carries `kid` so rotation is config, not code.
- **BYO-key encryption:** stop accepting per-request `byo_key`; store under `/users/me/byo-keys` encrypted with `APP_ENCRYPTION_KEY` (AES-GCM, random nonce, `nonce||ciphertext||tag`).
- **Tamper-evident audit log:** add `prev_hash` and `row_hash` to `decisions`. `row_hash = sha256(prev_hash || canonical_json(this_row))`. `GET /audit/verify` walks the chain and reports the first break. Deny DELETE at DB level on `decisions`/`decision_claims`/`retrieved_chunks`; corrections go in `decision_corrections`.
- **Structured logs** (`structlog`) with `request_id`, `tenant_id`, `user_id`. Redact passwords, tokens, BYO keys, full IPS body. Auth events persisted to `security_events`.
- **Input validation hardening:** body-size middleware (256 KB on `/ask`); `extra="forbid"` on all Pydantic models; regex on `client_code` (`^C[0-9]{3,6}$`).
- **Prompt-injection containment:** wrap retrieved chunks in `<source id="..."> ... </source>` tags; instruct the model that anything inside is data, not instructions.

**Done when:**
- `pytest backend/tests/test_phase_e_hardening.py` passes: CORS preflight rejects unknown origin; mutating a decision row triggers `/audit/verify` to flag the break; rate limit returns 429 with `Retry-After`; BYO key round-trip works without ever surfacing plaintext.

---

## Phase F — Frontend integration

**Goal:** real auth in the browser, end-to-end.

**Build:**
- Replace the fake login at [frontend/app/login/page.tsx](../frontend/app/login/page.tsx) with a real `POST /auth/login` call; handle MFA challenge, lockout, generic invalid-creds.
- `AuthProvider` React context: `{user, tenant, role, login, logout}`. Access token kept in memory only.
- `lib/api.ts` `request()` wrapped to:
  1. Attach `Authorization: Bearer ${access}`.
  2. On 401 → single in-flight `/auth/refresh` → retry once → on second 401, redirect to `/login`.
- Route guards in [frontend/app/app/layout.tsx](../frontend/app/app/layout.tsx); per-page role gates (admin tab requires `admin|owner`).
- New pages: `/login`, `/login/mfa`, `/accept-invite/[token]`, `/forgot`, `/reset/[token]`, `/app/settings/security` (change password, MFA, BYO keys, active sessions, "log out everywhere").
- Sidebar shows tenant name, user email, role badge. Admin tab gains Users (invite/revoke/role) and Audit-Verify cards.

**Done when:**
- Playwright e2e: unauth user redirected from `/app/*` to `/login`; full login → workbench → logout works; admin tab hidden for advisor role; refresh token rotates silently across `/ask` calls.

---

## Phase G — Tests & threat-model verification

**Goal:** lock in the invariants and produce a defensible threat model.

**Build:**
- Test additions in [backend/tests/](../backend/tests/):
  - Login, refresh-rotation, refresh-reuse detection, lockout, MFA happy + sad.
  - Tenant isolation across `/ask`, `/audit`, `/metrics`, `/models`, `/determinism`, `/clients`.
  - Role gates: advisor blocked from `/models/*`; another user's audit in same tenant blocked for advisor.
  - Hash-chain: mutate a row, verify endpoint reports break.
  - Rate-limit on `/auth/login`.
- `docs/threat-model.md`: STRIDE table for login, `/ask`, audit read, BYO-key storage, corpus ingest, prompt injection.

**Done when:**
- Full test suite green in CI.
- `docs/threat-model.md` reviewed and committed.

---

## Phased timing (rough)

| # | Phase | Days |
|---|---|---|
| A | Data foundation | 1–2 |
| B | Auth endpoints | 3–4 |
| C | Authorization | 2 |
| D | Corpus isolation | 2 |
| E | Hardening | 2–3 |
| F | Frontend wiring | 2 |
| G | Tests + threat model | 1–2 |

**Total:** ~13–17 dev days.

---

## Deliberately NOT in this pass

- AWS deploy (Cognito, RDS, Secrets Manager, KMS). Architecturally compatible — separate later phase.
- SSO (Okta / Azure AD). Add `auth_provider` to `users` later; SSO becomes one of several login routes.
- SOC2 / ISO27001 evidence collection.
- WebAuthn / passkeys (TOTP MFA first; passkeys later).
- Billing / subscription plumbing.

---

## Status tracker

- [x] Phase A — Data foundation
- [x] Phase B — Authentication
- [x] Phase C — Authorization & tenant scoping
- [x] Phase D — Corpus isolation
- [x] Phase E — Production hardening
- [x] Phase F — Frontend integration
- [x] Phase G — Tests + threat model

Update the checkbox **only** when the phase's acceptance test is green.
