# Phase 6 + Phase 7 — Codex Tasks

> One block at a time. Phase 6 is the headline novelty. Phase 7 makes it publicly usable for free.

---

## TASK — Phase 6: Determinism Harness

**Context:** Read BUILD-SPEC §7 (determinism harness paragraph), §3 (`DETERMINISM_RUNS`), §8 (P6). Measure how consistent the agent is — the part that makes this stand out.

**Do:**
1. `backend/app/core/trust_metrics.py`: add `determinism_run(question, client_id, runs=DETERMINISM_RUNS)` —
   - Run the full /ask pipeline `runs` times at temperature 0.1.
   - Normalize each answer (lowercase, strip whitespace/punctuation) and extract its claim/citation set.
   - Score = blend of (a) pairwise normalized-text similarity and (b) Jaccard overlap of claim-source sets across runs. Output 0–1.
2. Add `POST /determinism` endpoint: `{question, client_id}` → `{determinism_score, per_run_outcomes}`. Persist the score on a representative `decisions` row.
3. Optional comparison mode: accept an alternate model id, run the harness twice (default model vs alternate), return both scores. Write findings to `infra/aws-notes.md` or a `docs/determinism-findings.md` (short paragraph: which was more consistent, the accuracy trade-off you observed — this mirrors the known research result).
4. Feed avg determinism into `/metrics/summary`.

**Acceptance (BUILD-SPEC P6):** `POST /determinism` returns a 0–1 score; running it twice on the same question yields stable (close) scores. Add `tests/test_acceptance.py::test_p6_determinism`.

**Stop. Run P6, report the scores you observed.**

---

## TASK — Phase 7: Frontend + AWS Deploy + Public-Demo Hardening

> This is two sub-tasks. Do 7A (frontend) and 7B (deploy) as separate Codex runs if it's large.

### TASK 7A — Frontend (Next.js)
**Context:** Read BUILD-SPEC §2 (frontend tree), §5 (API contracts). Build the UI against the existing backend.

**Do:**
1. `frontend/lib/api.ts`: typed fetch helpers for `/ask`, `/audit`, `/audit/{id}`, `/metrics/summary`, `/determinism` using `FRONTEND_API_BASE`.
2. `app/page.tsx` + `components/ChatPanel.tsx`: advisor asks a question; show the answer with `SourceCitations.tsx` highlighting each cited source; show `TrustBadges.tsx` (grounding + determinism); clearly render refusals and fallbacks differently from answers.
3. `app/dashboard/page.tsx` + `components/MetricsCharts.tsx` (Recharts): live cards + charts for hallucination rate, refusal rate, avg determinism, audit completeness from `/metrics/summary`.
4. `app/audit/[id]/page.tsx`: replay view — question, retrieved chunks, each claim kept/dropped with its source, final outcome.
5. Optional: a "bring your own key" field that passes `byo_key` to `/ask`, stored only in component state (never sent anywhere except the backend call).

**Acceptance:** asking a question shows a cited answer; an out-of-scope question shows a refusal; the dashboard renders real numbers; an audit page replays a past decision.

### TASK 7B — AWS Deploy + Hardening
**Context:** Read BUILD-SPEC §3 (AWS env), §8 (P7), and README §6. Make it a free, public, rate-limited demo.

**Do:**
1. Add rate limiting to the backend (per-IP, `RATE_LIMIT_PER_MIN`); over-limit → HTTP 429 with a friendly JSON message. Add a simple in-process request queue so bursts degrade gracefully instead of failing hard.
2. `infra/aws-notes.md`: exact steps — EC2 (or Lambda+API Gateway) for the app, RDS Postgres for the audit DB, S3 for the corpus + Chroma store, an IAM role with least-privilege access, and how the frontend env points at the deployed backend. Include the billing-alarm setup ($20/$50/$100) and "never leave a GPU/large instance idle" warning.
3. Provide a minimal Dockerfile for the backend and document the deploy/run commands.
4. Ensure all secrets come from env / AWS, never committed.

**Acceptance (BUILD-SPEC P7):** the public URL responds; exceeding `RATE_LIMIT_PER_MIN` returns 429 with the friendly message; corpus loads from S3 in prod. Add `tests/test_acceptance.py::test_p7_ratelimit`.

**Stop. Report the live URL and confirm the rate limit works.**

---

## After Phase 7 — Polish (do yourself, not Codex)
- Record a short demo GIF/video; add screenshots to README.
- Write the `docs/design-decisions.md` (why no fine-tuning, why grounded-only, why open model + AWS split) — these are your interview answers.
- Paste the resume bullets from README §9, filling in the real `<X%>` numbers you measured.
