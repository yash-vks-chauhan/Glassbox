# Phase 0 + Phase 1 — Codex Tasks

> Paste ONE task block at a time into Codex. Wait for it to finish, run the acceptance check, commit, then move on. Both phases assume `README.md` and `BUILD-SPEC.md` are in the repo root and that Codex has read them.

---

## TASK — Phase 0: Project Setup

**Context:** You are building GlassBox. Read `BUILD-SPEC.md` sections 1–3 first. Use the exact stack and file tree specified there. Do not add alternatives or paid APIs.

**Do:**
1. Create the full folder tree from BUILD-SPEC §2 (empty files/`__init__.py` where needed).
2. `backend/requirements.txt` with: fastapi, uvicorn, pydantic-settings, sqlalchemy, alembic, psycopg[binary], chromadb, sentence-transformers, scikit-learn, joblib, httpx, python-dotenv, numpy, pytest.
3. `.env.example` exactly as in BUILD-SPEC §3.
4. `backend/app/config.py` using pydantic-settings to load every env var.
5. `docker-compose.yml` running Postgres 15 (db=glassbox, user/pass=glassbox).
6. `backend/app/main.py` with a FastAPI app and a `GET /health` returning `{"status":"ok"}`.
7. `backend/app/core/llm.py`: an OpenRouter client (httpx) with one function `chat(messages, temperature=None, model=None)` reading config; raise a typed `LLMUnavailable` on network/HTTP error.
8. A short `backend/README` note on how to run locally.

**Acceptance:** `uvicorn app.main:app` starts; `GET /health` returns ok; `llm.chat([{ "role":"user","content":"ping"}])` returns text when a key is set (skip gracefully if not).

**Stop after this. Report what you created and any decisions you had to make.**

---

## TASK — Phase 1: Corpus + Retrieval

**Context:** Read BUILD-SPEC §2, §4.1–4.3, §8 (P1). Build the document corpus and retrieval layer only. No LLM answering yet.

**Do:**
1. Create sample corpus files:
   - `corpus/ips/C001.md`, `C002.md`, `C003.md` — 3 clients with different risk profiles, using the exact YAML front-matter schema in BUILD-SPEC §4.1. Make C001 = moderate, max 25% single position, excludes tobacco/firearms, jurisdictions CH+US.
   - `corpus/factsheets/F100.md` (Global EM Equity, high risk), `F200.md` (Global Bond, low risk), `F300.md` (Tech Sector Equity, high risk) per §4.2.
   - `corpus/regulations/suitability.md` — 4–6 plain sentences on suitability basics (generic, public-knowledge phrasing).
2. `corpus/ingest.py`: parse front-matter + body, chunk by sentence/short paragraph, embed with `BAAI/bge-small-en-v1.5`, store in persistent Chroma at `CHROMA_DIR` with metadata per §4.3. Re-runnable (clears + reloads).
3. `backend/app/core/retrieval.py`: `retrieve(question, client_id=None, k=6)` → list of `{source_id, source_type, chunk_text, score}`, filtering by client_id when given.
4. `backend/data/test_questions.jsonl` with the 3 examples from BUILD-SPEC §4.5 plus 5 more.

**Acceptance (BUILD-SPEC P1):** running ingest then `retrieve("single position limit", client_id="C001")` returns the chunk containing the 25% rule within the top 3 results. Add this as a test in `tests/test_acceptance.py::test_p1_retrieval`.

**Stop after this. Run the P1 test and report pass/fail.**
