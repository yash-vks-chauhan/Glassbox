# GlassBox — Threat Model

Companion to [SECURITY-IMPLEMENTATION.md](SECURITY-IMPLEMENTATION.md). Phase G deliverable, updated October 2026.

This document enumerates threats by surface using STRIDE (Spoofing, Tampering,
Repudiation, Information disclosure, Denial of service, Elevation of privilege)
and maps each row to the **mitigation in code** plus the **test that locks it
in**. Code is referenced by file and function rather than line number, so the
references survive edits. It covers the multi-tenant application on SQLite or
Postgres; cloud-deployment threats (KMS, IAM, VPC) are outside its scope and
are handled in the deployment runbook ([infra/aws-notes.md](../infra/aws-notes.md)).

## Scope

- **Surfaces covered:** login and first-owner setup, `/ask` and threads,
  audit read and export, reviews, BYO-key storage, corpus ingest and the
  library, public endpoints, prompt injection.
- **Trust boundaries:**
  1. Browser ↔ FastAPI (untrusted client, TLS-only in prod).
  2. FastAPI ↔ SQLite/Postgres (trusted internal, but tamper-evident audit chain
     defends against operator-side manipulation).
  3. FastAPI ↔ LLM provider (semi-trusted; output is parsed as data, never
     executed; retrieved chunks are wrapped in `<source>` tags so prompt
     contents can't reissue instructions).
  4. Corpus filesystem (trusted writers only; path-traversal guard at ingest).
- **Assets:** session tokens, refresh cookies, MFA secrets, BYO LLM API keys,
  tenant client IPS, audit decisions, reviews and corrections, security event
  log.
- **Out of scope:** physical access, supply-chain attacks on Python deps
  (dependency advisories are checked in CI with pip-audit and npm audit),
  side-channel timing on the host CPU, social engineering of tenant users.

---

## 1. Login and first-owner setup (`/auth/*`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Credential stuffing / brute force | Attacker iterates emails+passwords | Account lockout after 5 failed attempts / 15 min via a **per-email** `failed_login_count` counter; generic error response for unknown email vs wrong password; Argon2id burned even on the unknown-user path (constant-ish timing). Per-IP rate budget is enforced separately by the auth-tier rate limiter (row 7), not by the lockout counter. | [service.py · `authenticate`](../backend/app/core/auth/service.py), [passwords.py · `verify_password`](../backend/app/core/auth/passwords.py); tests `test_lockout_after_max_failed_attempts`, `test_unknown_email_and_wrong_password_use_identical_error` |
| 2 | S — Account enumeration via `/auth/forgot` | Email-existence oracle | `/auth/forgot` always returns 200 regardless of email validity | [auth.py · `forgot_password`](../backend/app/routers/auth.py); test `test_forgot_password_always_returns_200_even_for_unknown_email` |
| 3 | T — Refresh token theft + replay | Stolen refresh token used after rotation | Refresh tokens are 256-bit random, hashed at rest, **rotated on every use**; reuse of a superseded token revokes the whole family | [service.py · `refresh_session`](../backend/app/core/auth/service.py); test `test_refresh_reuse_revokes_entire_family` |
| 4 | T — JWT forgery | Attacker forges access token | HS256 with a dedicated `JWT_SIGNING_KEY` from `scripts/init_secrets.py`; header must include a `kid`; algorithm allowlist refuses `alg=none`; production mode refuses to boot with the published dev key | [tokens.py · `decode_access_token`](../backend/app/core/auth/tokens.py), [config.py · `assert_secrets_safe_for_mode`](../backend/app/config.py); test `test_secrets_guard_blocks_production_with_default_jwt_key` |
| 5 | R — Disputed login | User claims they didn't sign in / lock out | Every login attempt persists a `security_events` row with `kind`, IP, UA; also written to structlog | [service.py · `_log_security_event`](../backend/app/core/auth/service.py) |
| 6 | I — Token leak via XSS | Access token exfiltrated by injected JS | Access token kept in module-scope JS memory only (never in localStorage); refresh cookie is `HttpOnly`, `Secure` (in prod), `SameSite=Lax`, scoped to the `/auth` path | [api.ts · `setAccessToken`](../frontend/lib/api.ts), [auth.py · `_set_refresh_cookie`](../backend/app/routers/auth.py) |
| 7 | D — Login flood | Attacker overwhelms auth tier | Persistent sliding-window rate limit: `/auth/*` 10/min per (user-or-IP); 429 + `Retry-After`. Behind a load balancer the client IP comes from `X-Forwarded-For`, trusted only from `FORWARDED_ALLOW_IPS` | [rate_limit.py](../backend/app/core/security/rate_limit.py); test `test_rate_limit_auth_tier_is_strict` |
| 8 | E — MFA bypass for high-privilege roles | Admin logs in without MFA | `MFA_REQUIRED_ROLES = {"owner", "admin"}` blocks login until MFA enrolled; TOTP via pyotp; recovery codes stored hashed and consumed once | [service.py · `MFA_REQUIRED_ROLES`, `authenticate`](../backend/app/core/auth/service.py); test `test_admin_must_enroll_mfa_before_login_completes` |
| 9 | I — MFA secrets read from a DB dump | `users.mfa_secret` copied | TOTP secret and recovery-code hashes stored as one AES-GCM blob (`enc:v1:<kid>:…`) with AAD bound to the user id, so a blob moved to another row won't open; older plaintext rows are converted by `scripts/encrypt_mfa_secrets.py` | [mfa.py · `pack_secret`, `unpack_secret`](../backend/app/core/auth/mfa.py); tests `test_mfa_secret_is_encrypted_at_rest_and_bound_to_its_user`, `test_encrypt_mfa_secrets_script_converts_plaintext_rows` |
| 10 | E — Stale token after tenant move / user delete | User moved to a different tenant; old JWT still valid until exp | `current_user` rejects when DB user's `tenant_id` no longer matches token `tid` | [deps.py · `current_user`](../backend/app/core/auth/deps.py); test `test_token_whose_user_no_longer_exists_is_401` |
| 11 | E — Second owner via first-owner setup | Leaked `BOOTSTRAP_SETUP_KEY` used on an existing workspace | Setup key compared in constant time; setup closes for a workspace once an owner or admin there has finished MFA; restarting an unfinished setup voids the earlier attempt's secret so its token can't complete | [service.py · `begin_bootstrap`, `_bootstrap_is_open`](../backend/app/core/auth/service.py); tests `test_bootstrap_closes_after_first_owner_exists`, `test_restarting_bootstrap_with_another_email_voids_the_first`, `test_bootstrap_wrong_setup_key_is_401` |

---

## 2. `/ask` and threads (the LLM hot path)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Unauthenticated ask | Drive-by request hits `/ask` | `require_role("advisor"+)` dependency; 401 without bearer | [ask.py · `ask`](../backend/app/routers/ask.py); test `test_unauthenticated_request_returns_401` |
| 2 | T — Cross-tenant client probe | User U1@T1 asks about T2's client C002 | `_validated_client_id` checks `client_code` exists *under caller's tenant*; 404 on miss (never 403) | [ask.py · `_validated_client_id`](../backend/app/routers/ask.py) |
| 3 | T — Cross-tenant corpus leak | T1 question retrieves T2's IPS | Retrieval filters chunks by `tenant_id` OR shared sentinel only; tenant_id pulled from the verified bearer | [retrieval.py · `_matches_tenant`](../backend/app/core/retrieval.py); test `test_t1_chunk_never_surfaces_in_t2_retrieval` |
| 4 | T — Path traversal via `client_id` | `client_id=../../../etc/passwd` | `SafeSourceId` Pydantic validator (regex + explicit `..` reject); `ClientCode` tightened to `^C[0-9]{3,6}$`; ingest-time `assert_safe_source_id` defends the filesystem boundary | [schemas.py · `_validate_source_id`](../backend/app/schemas.py), [ingest.py · `assert_safe_source_id`](../backend/corpus/ingest.py); test `test_ask_endpoint_rejects_traversal_client_id` |
| 5 | I — BYO key exfiltrated via prompt | Prompt-injection attack tricks LLM into echoing the API key | BYO keys never enter the LLM prompt; they're attached as `Authorization` to the outbound provider call. Plaintext crosses the network only on enrollment; storage is AES-GCM with AAD bound to `user_id` | [byo_keys.py](../backend/app/routers/byo_keys.py), [encryption.py](../backend/app/core/security/encryption.py); test `test_byo_key_endpoint_round_trip_never_returns_plaintext` |
| 6 | I — Sensitive payloads in logs | Question/answer contain client PII | structlog redaction processor strips known secret keys (`password`, `token`, `api_key`, `byo_key`, `authorization`, `cookie`, `mfa_code`) at serialise time | [logging.py · `_redact`](../backend/app/core/security/logging.py), `STRUCTLOG_REDACT_KEYS` |
| 7 | D — Body-size DoS | Multi-MB question payload to drain memory | Body-size middleware caps `/ask` at 256 KB (config: `BODY_MAX_BYTES_ASK`); 413 returned early via pure-ASGI receive interception | [body_size.py](../backend/app/core/security/body_size.py); test `test_body_size_middleware_rejects_oversized_ask` |
| 8 | D — `/ask` flood | Token spam at the LLM | Per-user rate limit 60/min on the `ask` class | [rate_limit.py · `_limit_for`](../backend/app/core/security/rate_limit.py) |
| 9 | E — Smuggling extra fields | Attacker injects `byo_key`/`tenant_id` in body | `StrictModel` Pydantic config (`extra="forbid"`) rejects unknown fields with 422 | [schemas.py · `StrictModel`, `AskRequest`](../backend/app/schemas.py); tests `test_ask_request_rejects_unknown_byo_key_field`, `test_ask_request_rejects_arbitrary_extra_field` |
| 10 | T — Asking inside someone else's thread | Reusing another advisor's `thread_id`, or one from another client or tenant, to borrow its context | A thread is bound to its tenant, its client and its owner; anything else is 404, or 422 for a client mismatch | [threads.py · `prepare_thread_for_ask`](../backend/app/core/threads.py); tests `test_only_the_owner_can_ask_in_a_thread`, `test_a_thread_is_bound_to_its_client`, `test_threads_are_tenant_scoped` |

---

## 3. Audit read, export and review (`/audit*`, `/reviews`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | S — Cross-tenant id enumeration | T2 user GETs `/audit/{T1-decision-id}` | Scoped query by `tenant_id`; missing row → 404 (never 403) | [audit.py · `get_audit`](../backend/app/routers/audit.py); test `test_cross_tenant_audit_returns_404_not_403` |
| 2 | I — Same-tenant info leak | Advisor reads another advisor's decisions | `_scoped_decision_query` adds `Decision.user_id == self.id` for advisor role; compliance/admin see tenant-wide | [audit.py · `_scoped_decision_query`](../backend/app/routers/audit.py); tests `test_advisor_sees_only_own_decisions_within_tenant`, `test_compliance_sees_other_advisors_decisions_in_same_tenant` |
| 3 | T — Operator silently rewrites an outcome | DBA flips `outcome` post-hoc | Tamper-evident SHA-256 hash chain across (decision, claims, chunks, and a follow-up's resolved question); `GET /audit/verify` walks the chain and reports first break; per-tenant chains keep verification scoped. A restart doesn't hide it: the startup backfill only links unhashed rows and never re-hashes one | [audit_hash.py](../backend/app/core/security/audit_hash.py), [db.py · `_backfill_audit_hash_chain_if_needed`](../backend/app/db.py); tests `test_mutating_a_decision_row_breaks_audit_verify`, `test_thread_context_is_covered_by_the_hash_chain` |
| 4 | T — Operator deletes a row to hide it | DBA runs `DELETE` or `TRUNCATE` on `decisions` | Database triggers on `decisions`, `decision_claims` and `retrieved_chunks`: `BEFORE DELETE` on SQLite, `BEFORE DELETE` and `BEFORE TRUNCATE` on Postgres; corrections must go in `decision_corrections` | [audit_guards.py](../backend/app/core/audit_guards.py); tests `test_db_level_delete_blocked_on_audit_tables`, `test_db_level_truncate_blocked_on_audit_tables` |
| 5 | T — Concurrent questions fork the chain | Two decisions in one tenant read the same chain tail | Appends hold a per-tenant lock (Postgres advisory lock; SQLite's writer lock) and are stamped under it, so the chain stays linear and a fork can't be passed off as, or hide, tampering | [audit_hash.py · `lock_tenant_chain`, `chain_timestamp`](../backend/app/core/security/audit_hash.py); test `test_concurrent_appends_in_one_tenant_keep_a_single_chain` |
| 6 | R — Auditor claims chain is intact when it isn't | `/audit/verify` permission too broad | Endpoint gated to `compliance|admin|owner`; advisors get 403 | [audit.py · `verify_audit_chain`](../backend/app/routers/audit.py); test `test_audit_verify_advisor_is_forbidden` |
| 7 | I — Bulk extraction via exports | Someone pulls the whole audit log as CSV/PDF | `/audit/export` is compliance+ and tenant-scoped, the PDF binder has a size cap, and every export is written to the security log | [audit.py · `export_audit`](../backend/app/routers/audit.py); tests `test_advisors_cannot_export`, `test_pdf_binder_export_is_logged`, `test_pdf_binder_refuses_oversized_selections` |
| 8 | T — Spreadsheet formula injection | A question like `=HYPERLINK(...)` executes when the CSV is opened | Cells starting with `=`, `+`, `-`, `@`, tab or CR are prefixed so spreadsheets treat them as text | [audit_export.py · `_csv_safe`](../backend/app/core/audit_export.py); test `test_csv_export_matches_filters_and_neutralises_formulas` |
| 9 | E — Self-approval | An advisor (or compliance user) reviews their own decision | Four-eyes rule: the person who asked can't review it; reviews are compliance+ and tenant-scoped; a review never edits the decision, it appends | [reviews.py · `submit_review`](../backend/app/core/reviews.py); tests `test_four_eyes_rule_blocks_reviewing_your_own_decision`, `test_advisors_cannot_submit_reviews`, `test_reviews_are_tenant_scoped` |
| 10 | D — Verify-chain expensive over millions of rows | Hostile loop spam on `/audit/verify` | `default` rate limit (120/min/subject) applies; chain walk is single SQL + Python sha256 (fast for our scale) | [rate_limit.py](../backend/app/core/security/rate_limit.py) |

---

## 4. BYO-key storage (`/users/me/byo-keys`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | I — DB dump exposes keys | `byo_keys` table read | AES-GCM ciphertext only (`base64(nonce || ct || tag)`); plaintext is **never persisted** and never returned by the API after enrollment | [encryption.py](../backend/app/core/security/encryption.py); test `test_byo_key_endpoint_round_trip_never_returns_plaintext` |
| 2 | T — Ciphertext copied to another user | Attacker swaps `byo_keys.user_id` and decrypts under their own token | AAD bound to `byo_key:<user_id>`; decrypt fails (tag mismatch) when AAD doesn't match | [byo_keys.py · `_aad_for`](../backend/app/routers/byo_keys.py), [encryption.py · `encrypt`](../backend/app/core/security/encryption.py); test `test_encrypt_with_aad_rejects_wrong_aad` |
| 3 | T — Cross-user fetch | User U asks for V's key via `?user_id=V` | Routes are bound to `current_user`; queries are `WHERE user_id == user.id`; no user-id parameter accepted | [byo_keys.py · `list_byo_keys`, `upsert_byo_key`, `delete_byo_key`](../backend/app/routers/byo_keys.py) |
| 4 | I — Plaintext key in logs | LLM router or HTTP client logs the auth header | structlog redaction list includes `api_key`, `authorization`, `byo_key`; `safe_last4` is the only display surface | [logging.py · `_redact`](../backend/app/core/security/logging.py), [encryption.py · `safe_last4`](../backend/app/core/security/encryption.py) |
| 5 | E — Advisors spending on their own keys | An advisor routes client questions through an unvetted personal model | BYO keys are an admin/owner tool unless `ALLOW_ADVISOR_BYO_KEYS=1` | [byo_keys.py · `byo_keys_allowed`](../backend/app/routers/byo_keys.py); test `test_byo_keys_are_admin_only_unless_policy_allows_advisors` |
| 6 | I — Memory dump | OS-level adversary reads process memory | Out of scope for this phase. Cloud phase (KMS-backed decryption) will narrow the window. | — |
| 7 | E — Forge keys with weak env | Operator runs with `APP_ENCRYPTION_KEY=dev-...` | `scripts/init_secrets.py` emits real 32-byte material, and production mode refuses to boot while any secret is a published dev default. Rotation keeps old ciphertext readable through `APP_ENCRYPTION_PREVIOUS_KEYS` | [config.py · `assert_secrets_safe_for_mode`](../backend/app/config.py); tests `test_secrets_guard_lists_every_offender_in_one_shot`, `test_secrets_guard_passes_when_all_rotated` |

---

## 5. Corpus ingest and the library (`backend/corpus/ingest.py`, `/library`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | T — Path traversal via filename | `corpus/tenants/{tid}/ips/../../shared/foo.md` | Source-id allowlist regex (`[A-Za-z0-9._-]{1,64}`) + explicit `..` reject in `assert_safe_source_id`; symlinks under tenant root skipped | [ingest.py · `_SAFE_SOURCE_ID`, `assert_safe_source_id`, `build_chunks`](../backend/corpus/ingest.py); tests `test_assert_safe_source_id_rejects_traversal`, `test_assert_safe_source_id_accepts_safe_ids` |
| 2 | T — IPS document forges its tenant in frontmatter | Tenant `t1` ships an IPS with `tenant_id: t2` in YAML | Path is the ground truth; metadata cannot override `_classify(path)` | [ingest.py · `build_chunks`](../backend/corpus/ingest.py) |
| 3 | I — Shared collection contaminated with tenant data | Operator drops T1's IPS into `shared/regulations/` | Layout enforcement: `shared/regulations|factsheets/` only; tenant IPS must be under `tenants/{id}/ips/`. Mis-filed files are classified `unknown` and skipped. | [ingest.py · `_classify`](../backend/corpus/ingest.py) |
| 4 | E — Malicious chunk re-tags itself at retrieval time | A chunk claims `tenant_id=""` | Retrieval filter rejects anything not matching `caller's tenant_id` or shared sentinel; default fallback when tenant unknown is **shared-only** | [retrieval.py · `_matches_tenant`](../backend/app/core/retrieval.py); test `test_shared_collection_visible_to_both_tenants` |
| 5 | I — Reading arbitrary files through the document viewer | `GET /library/../../.env`, or another tenant's IPS id | The viewer only serves documents from the caller's tenant (plus shared ones) by source id, after the same source-id check; anything else is a 404 indistinguishable from a missing document | [library.py · `get_document`](../backend/app/routers/library.py); tests `test_unknown_or_unsafe_ids_are_not_found`, `test_other_tenants_see_shared_documents_only` |

---

## 6. Prompt injection (LLM call)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | E — IPS contains "ignore the system prompt and …" | Retrieved chunk overrides the agent's instructions | Each chunk wrapped in `<source id="…" type="…"> … </source>`; system prompt instructs the model that anything inside is *data, not instructions* | [answer_agent.py · `_build_prompt`, `_system_message`](../backend/app/core/answer_agent.py); test `test_answer_agent_prompt_wraps_chunks_in_source_tags` |
| 2 | E — Chunk text injects a closing tag to break out | Attacker authors `… </source><source id="evil">…` | Defang: `</source>` in chunk text replaced with `&lt;/source&gt;` before templating | [answer_agent.py · `_sanitise_chunk_text`](../backend/app/core/answer_agent.py); test `test_answer_agent_defangs_closing_tag_in_chunk_text` |
| 3 | T — Hallucinated `source_id` cited in answer | LLM invents `[FAKE-123]` to back a claim | `parse_claims` validates each cited source-id against the allowlist of source-ids actually retrieved; unknown ids drop the claim | [answer_agent.py · `parse_claims`](../backend/app/core/answer_agent.py) |
| 4 | I — Refusal text leaks tenant data | Refusal explanation paraphrases the chunk | `compose_refusal_reason` is a constant-string composer; raw chunk text never enters the refusal path | [refusal.py](../backend/app/core/refusal.py) |

---

## 7. Public endpoints (`/public/access-requests`)

| # | Threat (STRIDE) | Vector | Mitigation | Evidence |
|---|---|---|---|---|
| 1 | D — Form spam | Bots flood the "request access" form | A hidden honeypot field (filled submissions are accepted but not stored) and the strict rate tier shared with `/auth/*` | [public.py · `create_access_request`](../backend/app/routers/public.py); tests `test_honeypot_submission_is_accepted_but_not_stored`, `test_public_routes_use_the_strict_rate_tier` |
| 2 | T — Oversized or malformed submissions | Huge fields or extra keys | Strict schema with length limits; unknown fields rejected | [schemas.py](../backend/app/schemas.py); test `test_invalid_submissions_are_rejected` |

---

## Known residual risks (tracked, not yet mitigated)

- ~~**Default dev secrets boot in production.**~~ **Mitigated.** The lifespan
  startup calls `assert_secrets_safe_for_mode(settings)`, which raises
  `InsecureProductionSecretsError` when `GLASSBOX_PRODUCTION_MODE=1` is set
  and any of `JWT_SIGNING_KEY` / `APP_ENCRYPTION_KEY` / `COOKIE_SECRET` is
  still the published `dev-insecure-…` value. The error lists every
  offender at once and points at `scripts/init_secrets.py`. Evidence:
  [config.py · `assert_secrets_safe_for_mode`](../backend/app/config.py),
  [main.py · `lifespan`](../backend/app/main.py); tests
  `test_secrets_guard_blocks_production_with_default_jwt_key`,
  `test_secrets_guard_lists_every_offender_in_one_shot`,
  `test_secrets_guard_passes_when_all_rotated`,
  `test_secrets_guard_no_op_when_not_production`.
- ~~**SQLite operational ceiling.**~~ **Mitigated.** Postgres is supported
  end to end: equivalent delete and truncate guards, the same hash chain with
  an advisory lock for concurrent appends, and the full suite runs on
  Postgres in CI. The rate limiter stays database-backed, which is shared
  across replicas but costs a write per request; move it to Redis if
  traffic grows.
- **Setup key creates workspaces.** While `BOOTSTRAP_SETUP_KEY` is set,
  anyone holding it can create a new, empty workspace and own it. It can't
  touch an existing workspace whose owner has enrolled MFA. Unset it after
  first-owner setup (the runbook says so).
- **No WebAuthn.** TOTP only for now; phishing-resistant MFA arrives in a
  later phase (see "Deliberately NOT in this pass" in
  [SECURITY-IMPLEMENTATION.md](SECURITY-IMPLEMENTATION.md)).
- **No SSO.** `auth_provider` column not yet on `users`; planned for the Okta
  / Entra ID pass.
- **Memory-level adversary.** Process-memory snapshots can recover BYO key
  plaintext between decrypt and the outbound HTTP call. KMS-backed decryption
  (cloud phase) narrows the window.

---

## Verification matrix

Each row above either links to a test or is explicitly flagged as a tracked
residual risk. On 2 October 2026 the backend suite was green at **243 passed**
on SQLite (plus 5 Postgres-only tests skipped there) and **248 passed** on
Postgres 15; CI runs both on every pull request, plus the Playwright suite.
