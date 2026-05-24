# GlassBox — Threat Model

Companion to [SECURITY-IMPLEMENTATION.md](SECURITY-IMPLEMENTATION.md). Phase G deliverable.

This document enumerates threats by surface using STRIDE (Spoofing, Tampering,
Repudiation, Information disclosure, Denial of service, Elevation of privilege)
and maps each row to the **mitigation in code** plus the **test that locks it
in**. It assumes the system is locally-deployed multi-tenant per Phase A–F; the
cloud-deploy threats (KMS, IAM, VPC) are explicitly out of scope and tracked
in a separate deployment hardening pass.

## Scope

- **Surfaces covered:** login flow, `/ask`, audit read, BYO-key storage, corpus
  ingest, prompt injection.
- **Trust boundaries:**
  1. Browser ↔ FastAPI (untrusted client, TLS-only in prod).
  2. FastAPI ↔ SQLite/Postgres (trusted internal, but tamper-evident audit chain
     defends against operator-side manipulation).
  3. FastAPI ↔ LLM provider (semi-trusted; output is parsed as data, never
     executed; retrieved chunks are wrapped in `<source>` tags so prompt
     contents can't reissue instructions).
  4. Corpus filesystem (trusted writers only; path-traversal guard at ingest).
- **Assets:** session tokens, refresh cookies, BYO LLM API keys, tenant client
  IPS, audit decisions, security event log.
- **Out of scope:** physical access, supply-chain attacks on Python deps,
  side-channel timing on the host CPU, social engineering of tenant users.

---

## 1. Login flow (`/auth/login`, `/auth/refresh`, `/auth/logout`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Credential stuffing / brute force | Attacker iterates emails+passwords | Account lockout after 5 failed attempts / 15 min via a **per-email** `failed_login_count` counter; generic error response for unknown email vs wrong password; Argon2id burned even on the unknown-user path (constant-ish timing). Per-IP rate budget is enforced separately by the auth-tier rate limiter (row 7), not by the lockout counter. | [service.py:188-208](../backend/app/core/auth/service.py#L188-L208), [passwords.py:92-112](../backend/app/core/auth/passwords.py#L92-L112); tests `test_lockout_after_max_failed_attempts`, `test_unknown_email_and_wrong_password_use_identical_error` |
| 2 | S — Account enumeration via `/auth/forgot` | Email-existence oracle | `/auth/forgot` always returns 200 regardless of email validity | [auth.py:189-203](../backend/app/routers/auth.py#L189-L203); test `test_forgot_password_always_returns_200_even_for_unknown_email` |
| 3 | T — Refresh token theft + replay | Stolen refresh token used after rotation | Refresh tokens are 256-bit random, hashed at rest, **rotated on every use**; reuse of a superseded token revokes the whole family | [service.py:343-407](../backend/app/core/auth/service.py#L343-L407); test `test_refresh_reuse_revokes_entire_family` |
| 4 | T — JWT forgery | Attacker forges access token | HS256 with a dedicated `JWT_SIGNING_KEY` from `scripts/init_secrets.py`; header must include a `kid`; algorithm allowlist refuses `alg=none` | [tokens.py:66-93](../backend/app/core/auth/tokens.py#L66-L93) |
| 5 | R — Disputed login | User claims they didn't sign in / lock out | Every login attempt persists a `security_events` row with `kind`, IP, UA; also written to structlog | [service.py:617-639](../backend/app/core/auth/service.py#L617-L639) |
| 6 | I — Token leak via XSS | Access token exfiltrated by injected JS | Access token kept in module-scope JS memory only (never in localStorage); refresh cookie is `HttpOnly`, `Secure` (in prod), `SameSite=Lax`, scoped to `/auth/refresh` | [api.ts:150-173](../frontend/lib/api.ts#L150-L173), [auth.py:54-72](../backend/app/routers/auth.py#L54-L72) |
| 7 | D — Login flood | Attacker overwhelms auth tier | Persistent sliding-window rate limit: `/auth/*` 10/min per (user-or-IP); 429 + `Retry-After` | [rate_limit.py](../backend/app/core/security/rate_limit.py); test `test_rate_limit_auth_tier_is_strict` |
| 8 | E — MFA bypass for high-privilege roles | Admin logs in without MFA | `MFA_REQUIRED_ROLES = {"owner", "admin"}` blocks login until MFA enrolled; TOTP via pyotp; recovery codes consumed once | [service.py:57-58](../backend/app/core/auth/service.py#L57-L58), [service.py:235-239](../backend/app/core/auth/service.py#L235-L239); test `test_admin_must_enroll_mfa_before_login_completes` |
| 9 | E — Stale token after tenant move / user delete | User moved to a different tenant; old JWT still valid until exp | `current_user` rejects when DB user's `tenant_id` no longer matches token `tid` | [deps.py:56-63](../backend/app/core/auth/deps.py#L56-L63); test `test_token_whose_user_no_longer_exists_is_401` |

---

## 2. `/ask` (the LLM hot path)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Unauthenticated ask | Drive-by request hits `/ask` | `require_role("advisor"+)` dependency; 401 without bearer | [ask.py:52-67](../backend/app/routers/ask.py#L52-L67); test `test_unauthenticated_request_returns_401` |
| 2 | T — Cross-tenant client probe | User U1@T1 asks about T2's client C002 | `_validated_client_id` checks `client_code` exists *under caller's tenant*; 404 on miss (never 403) | [ask.py:32-49](../backend/app/routers/ask.py#L32-L49) |
| 3 | T — Cross-tenant corpus leak | T1 question retrieves T2's IPS | Retrieval filters chunks by `tenant_id` OR shared sentinel only; tenant_id pulled from the verified bearer | [retrieval.py:65-82](../backend/app/core/retrieval.py#L65-L82); test `test_t1_chunk_never_surfaces_in_t2_retrieval` |
| 4 | T — Path traversal via `client_id` | `client_id=../../../etc/passwd` | `SafeSourceId` Pydantic validator (regex + explicit `..` reject); `ClientCode` tightened to `^C[0-9]{3,6}$`; ingest-time `assert_safe_source_id` defends the filesystem boundary | [schemas.py:24-39](../backend/app/schemas.py#L24-L39), [ingest.py:39-50](../backend/corpus/ingest.py#L39-L50); test `test_ask_endpoint_rejects_traversal_client_id` |
| 5 | I — BYO key exfiltrated via prompt | Prompt-injection attack tricks LLM into echoing the API key | BYO keys never enter the LLM prompt; they're attached as `Authorization` to the outbound provider call. Plaintext crosses the network only on enrollment; storage is AES-GCM with AAD bound to `user_id` | [byo_keys.py](../backend/app/routers/byo_keys.py), [encryption.py](../backend/app/core/security/encryption.py); test `test_byo_key_endpoint_round_trip_never_returns_plaintext` |
| 6 | I — Sensitive payloads in logs | Question/answer contain client PII | structlog redaction processor strips known secret keys (`password`, `token`, `api_key`, `byo_key`, `authorization`, `cookie`, `mfa_code`) at serialise time | [logging.py:76-93](../backend/app/core/security/logging.py#L76-L93), `STRUCTLOG_REDACT_KEYS` |
| 7 | D — Body-size DoS | Multi-MB question payload to drain memory | Body-size middleware caps `/ask` at 256 KB (config: `BODY_MAX_BYTES_ASK`); 413 returned early via pure-ASGI receive interception | [body_size.py](../backend/app/core/security/body_size.py); test `test_body_size_middleware_rejects_oversized_ask` |
| 8 | D — `/ask` flood | Token spam at the LLM | Per-user rate limit 60/min on the `ask` class | [rate_limit.py:79-103](../backend/app/core/security/rate_limit.py#L79-L103) |
| 9 | E — Smuggling extra fields | Attacker injects `byo_key`/`tenant_id` in body | `StrictModel` Pydantic config (`extra="forbid"`) rejects unknown fields with 422 | [schemas.py:20-22](../backend/app/schemas.py#L20-L22), [schemas.py:126-136](../backend/app/schemas.py#L126-L136); tests `test_ask_request_rejects_unknown_byo_key_field`, `test_ask_request_rejects_arbitrary_extra_field` |

---

## 3. Audit read (`/audit`, `/audit/{id}`, `/audit/verify`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Cross-tenant id enumeration | T2 user GETs `/audit/{T1-decision-id}` | Scoped query by `tenant_id`; missing row → 404 (never 403) | [audit.py:76-90](../backend/app/routers/audit.py#L76-L90); test `test_cross_tenant_audit_returns_404_not_403` |
| 2 | I — Same-tenant info leak | Advisor reads another advisor's decisions | `_scoped_decision_query` adds `Decision.user_id == self.id` for advisor role; compliance/admin see tenant-wide | [audit.py:27-32](../backend/app/routers/audit.py#L27-L32); tests `test_advisor_sees_only_own_decisions_within_tenant`, `test_compliance_sees_other_advisors_decisions_in_same_tenant` |
| 3 | T — Operator silently rewrites an outcome | DBA flips `outcome` post-hoc | Tamper-evident SHA-256 hash chain across (decision, claims, chunks); `GET /audit/verify` walks the chain and reports first break; per-tenant chains keep verification scoped | [audit_hash.py](../backend/app/core/security/audit_hash.py); test `test_mutating_a_decision_row_breaks_audit_verify` |
| 4 | T — Operator deletes a row to hide it | DBA runs `DELETE FROM decisions` | SQLite `BEFORE DELETE` triggers on `decisions`, `decision_claims`, `retrieved_chunks` raise an abort; corrections must go in `decision_corrections` | [0005_phase_e_hardening.py:72-81](../backend/alembic/versions/0005_phase_e_hardening.py#L72-L81); test `test_db_level_delete_blocked_on_audit_tables` |
| 5 | R — Auditor claims chain is intact when it isn't | `/audit/verify` permission too broad | Endpoint gated to `compliance|admin|owner`; advisors get 403 | [audit.py:52-73](../backend/app/routers/audit.py#L52-L73); test `test_audit_verify_advisor_is_forbidden` |
| 6 | D — Verify-chain expensive over millions of rows | Hostile loop spam on `/audit/verify` | `default` rate limit (120/min/subject) applies; chain walk is single SQL + Python sha256 (fast for our scale) | [rate_limit.py](../backend/app/core/security/rate_limit.py) |

---

## 4. BYO-key storage (`/users/me/byo-keys`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | I — DB dump exposes keys | `byo_keys` table read | AES-GCM ciphertext only (`base64(nonce || ct || tag)`); plaintext is **never persisted** and never returned by the API after enrollment | [encryption.py](../backend/app/core/security/encryption.py); test `test_byo_key_endpoint_round_trip_never_returns_plaintext` |
| 2 | T — Ciphertext copied to another user | Attacker swaps `byo_keys.user_id` and decrypts under their own token | AAD bound to `byo_key:<user_id>`; decrypt fails (tag mismatch) when AAD doesn't match | [byo_keys.py:60-61](../backend/app/routers/byo_keys.py#L60-L61), [encryption.py:74-87](../backend/app/core/security/encryption.py#L74-L87); test `test_encrypt_with_aad_rejects_wrong_aad` |
| 3 | T — Cross-user fetch | User U asks for V's key via `?user_id=V` | Routes are bound to `current_user`; queries are `WHERE user_id == user.id`; no user-id parameter accepted | [byo_keys.py:64-118](../backend/app/routers/byo_keys.py#L64-L118) |
| 4 | I — Plaintext key in logs | LLM router or HTTP client logs the auth header | structlog redaction list includes `api_key`, `authorization`, `byo_key`; `safe_last4` is the only display surface | [logging.py:76-93](../backend/app/core/security/logging.py#L76-L93), [encryption.py:106-111](../backend/app/core/security/encryption.py#L106-L111) |
| 5 | I — Memory dump | OS-level adversary reads process memory | Out of scope for this phase. Cloud phase (KMS-backed decryption) will narrow the window. |
| 6 | E — Forge keys with weak env | Operator runs with `APP_ENCRYPTION_KEY=dev-...` | `scripts/init_secrets.py` emits real 32-byte material; key acceptance still SHA-256s arbitrary strings down to 32 bytes for dev only. Production-mode hardening should reject default values (open follow-up). |

---

## 5. Corpus ingest (`backend/corpus/ingest.py`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | T — Path traversal via filename | `corpus/tenants/{tid}/ips/../../shared/foo.md` | Source-id allowlist regex (`[A-Za-z0-9._-]{1,64}`) + explicit `..` reject in `assert_safe_source_id`; symlinks under tenant root skipped | [ingest.py:31-50](../backend/corpus/ingest.py#L31-L50), [ingest.py:155-167](../backend/corpus/ingest.py#L155-L167); tests `test_assert_safe_source_id_rejects_traversal`, `test_assert_safe_source_id_accepts_safe_ids` |
| 2 | T — IPS document forges its tenant in frontmatter | Tenant `t1` ships an IPS with `tenant_id: t2` in YAML | Path is the ground truth; metadata cannot override `_classify(path)` | [ingest.py:170-198](../backend/corpus/ingest.py#L170-L198) |
| 3 | I — Shared collection contaminated with tenant data | Operator drops T1's IPS into `shared/regulations/` | Layout enforcement: `shared/regulations|factsheets/` only; tenant IPS must be under `tenants/{id}/ips/`. Mis-filed files are classified `unknown` and skipped. | [ingest.py:104-134](../backend/corpus/ingest.py#L104-L134) |
| 4 | E — Malicious chunk re-tags itself at retrieval time | A chunk claims `tenant_id=""` | Retrieval filter rejects anything not matching `caller's tenant_id` or shared sentinel; default fallback when tenant unknown is **shared-only** | [retrieval.py:65-82](../backend/app/core/retrieval.py#L65-L82); test `test_shared_collection_visible_to_both_tenants` |

---

## 6. Prompt injection (LLM call)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | E — IPS contains "ignore the system prompt and …" | Retrieved chunk overrides the agent's instructions | Each chunk wrapped in `<source id="…" type="…"> … </source>`; system prompt instructs the model that anything inside is *data, not instructions* | [answer_agent.py:55-83](../backend/app/core/answer_agent.py#L55-L83); test `test_answer_agent_prompt_wraps_chunks_in_source_tags` |
| 2 | E — Chunk text injects a closing tag to break out | Attacker authors `… </source><source id="evil">…` | Defang: `</source>` in chunk text replaced with `&lt;/source&gt;` before templating | [answer_agent.py:55-60](../backend/app/core/answer_agent.py#L55-L60); test `test_answer_agent_defangs_closing_tag_in_chunk_text` |
| 3 | T — Hallucinated `source_id` cited in answer | LLM invents `[FAKE-123]` to back a claim | `parse_claims` validates each cited source-id against the allowlist of source-ids actually retrieved; unknown ids drop the claim | [answer_agent.py:88-110](../backend/app/core/answer_agent.py#L88-L110) |
| 4 | I — Refusal text leaks tenant data | Refusal explanation paraphrases the chunk | `compose_refusal_reason` is a constant-string composer; raw chunk text never enters the refusal path | [refusal.py](../backend/app/core/refusal.py) |

---

## Known residual risks (tracked, not yet mitigated)

- ~~**Default dev secrets boot in production.**~~ **Mitigated.** The lifespan
  startup now calls `assert_secrets_safe_for_mode(settings)` which raises
  `InsecureProductionSecretsError` when `GLASSBOX_PRODUCTION_MODE=1` is set
  and any of `JWT_SIGNING_KEY` / `APP_ENCRYPTION_KEY` / `COOKIE_SECRET` is
  still the published `dev-insecure-…` value. The error lists every
  offender at once and points at `scripts/init_secrets.py`. Evidence:
  [config.py — assert_secrets_safe_for_mode](../backend/app/config.py),
  [main.py:lifespan](../backend/app/main.py); tests
  `test_secrets_guard_blocks_production_with_default_jwt_key`,
  `test_secrets_guard_lists_every_offender_in_one_shot`,
  `test_secrets_guard_passes_when_all_rotated`,
  `test_secrets_guard_no_op_when_not_production`.
- **SQLite operational ceiling.** The rate-limiter, audit chain, and DELETE
  guards are all SQLite-backed. Migrating to Postgres needs equivalent
  `BEFORE DELETE` triggers + a Redis-backed limiter (the limiter's interface
  was kept narrow for exactly this).
- **No WebAuthn.** TOTP only for now; phishing-resistant MFA arrives in a
  later phase (see "Deliberately NOT in this pass" in
  [SECURITY-IMPLEMENTATION.md](SECURITY-IMPLEMENTATION.md)).
- **No SSO.** `auth_provider` column not yet on `users`; planned for the Okta
  / Azure-AD pass.
- **Memory-level adversary.** Process-memory snapshots can recover BYO key
  plaintext between decrypt and the outbound HTTP call. KMS-backed decryption
  (cloud phase) narrows the window.

---

## Verification matrix

Each row above either links to a test or is explicitly flagged as a tracked
residual risk. The full pytest suite (`pytest backend/tests/`) was green at
**127 passed** at the time of writing.
