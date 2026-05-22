# Phase 4 + Phase 5 — Codex Tasks

> One block at a time. Phase 4 makes everything auditable. Phase 5 adds the models that make the project *yours*.

---

## TASK — Phase 4: Provenance Logger + Audit DB

**Context:** Read BUILD-SPEC §4.4 (tables), §5 (audit endpoints), §7 step 8, §8 (P4). Persist and replay every decision.

**Do:**
1. `backend/app/db.py`: SQLAlchemy engine + session from `DATABASE_URL`.
2. `backend/app/models_db.py`: ORM for `decisions`, `decision_claims`, `retrieved_chunks` exactly per BUILD-SPEC §4.4.
3. Alembic init + first migration creating those tables.
4. `backend/app/core/provenance.py`: `record_decision(...)` writing one `decisions` row + child `decision_claims` + `retrieved_chunks` in a transaction; returns decision_id.
5. Call it at the end of every `/ask` (answered, refused, and later fallback).
6. `backend/app/routers/audit.py`: `GET /audit?limit=50` (summaries) and `GET /audit/{id}` (full replay payload).

**Acceptance (BUILD-SPEC P4):** after an `/ask`, `GET /audit/{id}` returns the question, all retrieved_chunks, all decision_claims (kept+dropped), and final outcome — enough to fully reconstruct the decision. Add `tests/test_acceptance.py::test_p4_provenance`.

**Stop. Run P4, report pass/fail.**

---

## TASK — Phase 5: Trust Models (our scikit-learn models) + Fallback

**Context:** Read BUILD-SPEC §6 (all three model specs), §7 steps 3,7,9, §8 (P5). Build training scripts, wire models into the pipeline, add offline fallback.

**Do:**
1. Generate labeled training data into `backend/data/training/`:
   - `grounding.jsonl` (~300 rows), `refusal.jsonl` (~200 rows), `fallback.jsonl` (~150 rows) per §6. Write a small generator that builds positives from corpus sentences and negatives by mismatching sources / mutating numbers. Commit both the generator and the generated files.
2. `backend/app/ml/train_grounding.py`, `train_refusal.py`, `train_fallback.py` — each: load data → features per §6 → train → print accuracy + F1 → save `.joblib` to `app/ml/artifacts/`.
3. `backend/app/core/trust_metrics.py`: load grounding model; `grounding_score(claims)` = mean supported-prob of kept claims. Wire into `/ask` response `trust.grounding_score` and persist on the `decisions` row.
4. Wire the refusal router into `refusal.py` as a second signal alongside the 0.35 threshold.
5. `backend/app/core/fallback.py`: on `LLMUnavailable` in answer/verify, load fallback model, return a valid `/ask` response with `outcome:"fallback"`. Log it like any decision.
6. `backend/app/routers/metrics.py`: `GET /metrics/summary` per BUILD-SPEC §5 — compute hallucination_rate (share of low-grounding answers), refusal_rate, avg_determinism (nullable for now), audit_completeness from the DB.

**Acceptance (BUILD-SPEC P5):** `/metrics/summary` returns a non-null hallucination_rate derived from the grounding model; temporarily unsetting `OPENROUTER_API_KEY` makes `/ask` return a valid `fallback` response instead of erroring. Add `tests/test_acceptance.py::test_p5_trust_and_fallback`.

**Stop. Run P5, report each model's accuracy/F1 and pass/fail.**
