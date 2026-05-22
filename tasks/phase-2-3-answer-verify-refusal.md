# Phase 2 + Phase 3 — Codex Tasks

> Paste one block at a time. These build the reasoning core. Requires Phases 0–1 complete and passing.

---

## TASK — Phase 2: Answer Agent + Grounding

**Context:** Read BUILD-SPEC §5 (POST /ask), §7 steps 1–2 & 4, §8 (P2). Build grounded answer drafting. Verification comes in Phase 3 — keep them separate.

**Do:**
1. `backend/app/schemas.py`: pydantic models for the /ask request and response exactly per BUILD-SPEC §5.
2. `backend/app/core/answer_agent.py`: `draft_answer(question, retrieved_chunks)` →
   - System prompt instructs: answer ONLY from the provided chunks; every sentence must end with a `[source_id]` tag; if nothing supports an answer, say exactly `INSUFFICIENT_CONTEXT`.
   - Temperature from config (0.1). Returns raw draft text.
3. A parser that splits the draft into `(claim_text, cited_source_id)` pairs and **drops any claim whose cited source_id is not in the retrieved set** (anti-hallucination guard).
4. `backend/app/routers/ask.py`: wire `POST /ask` for the happy path only — retrieve → draft → strip uncited → return answer + citations. (Refusal/verify added next phase; for now if draft is `INSUFFICIENT_CONTEXT`, return outcome `refused` with a generic reason.)
5. Register the router in `main.py`.

**Acceptance (BUILD-SPEC P2):** for an in-corpus question, every returned citation's `source_id` exists in the retrieved set, and no uncited claim appears in the answer. Add `tests/test_acceptance.py::test_p2_grounding`.

**Stop. Run P2, report pass/fail and any prompt wording you chose.**

---

## TASK — Phase 3: Verify Agent + Refusal

**Context:** Read BUILD-SPEC §7 steps 3,5,6 and §8 (P3). Add the verification pass and refusal/escalation logic on top of Phase 2.

**Do:**
1. `backend/app/core/verify_agent.py`: `verify_claims(claims)` implementing Chain-of-Verification —
   - For each `(claim, cited_chunk)`, ask the LLM a yes/no: "Is this claim fully supported by this source text?" Parse strictly to bool.
   - Drop claims that fail. Return kept claims + dropped claims (for logging).
2. `backend/app/core/refusal.py`: `should_refuse(question, retrieved)` →
   - Refuse if max retrieval score < 0.35 (threshold from spec), OR no chunks, OR all claims dropped during verify.
   - Return `(refuse: bool, reason: str)`.
3. Update `routers/ask.py` to the full step order in BUILD-SPEC §7 (retrieve → refusal check → draft → verify → assemble or refuse). If everything is dropped, outcome = `refused`.
4. Ensure the 3 canonical test questions behave per their `expect` field.

**Acceptance (BUILD-SPEC P3):** the German-tax question → `refused`; the C001 "40% into F100" question → `refused` or an explained violation; an in-profile suitability question → `answered`. Add `tests/test_acceptance.py::test_p3_verify_refusal`.

**Stop. Run P3, report pass/fail.**
