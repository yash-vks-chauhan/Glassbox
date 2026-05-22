# GlassBox — Build Spec (Frozen Decisions)

> **Purpose of this file:** remove every ambiguity so a coding agent (Codex/ChatGPT) builds the *same* system every time, with no guessing. Read together with `README.md`. The README = *what & why*. This = *exact how*.
>
> **How to use with Codex:** do NOT paste this whole file as one task. Use the phase prompts in `tasks/phase-*.md`, one at a time. This file is the shared reference both you and the agent rely on.

---

## 1. Frozen Tech Stack (no alternatives — use exactly these)

| Job | Locked choice | Version / id |
|---|---|---|
| Language | Python | 3.11 |
| Backend framework | FastAPI | latest |
| LLM provider | **OpenRouter** (free tier) | base url `https://openrouter.ai/api/v1` |
| LLM model (default) | `meta-llama/llama-3.3-70b-instruct:free` | swappable via env |
| LLM model (BYO-key optional) | user-supplied | — |
| Embeddings | sentence-transformers `BAAI/bge-small-en-v1.5` | local, CPU |
| Vector DB | **Chroma** (persistent, file-based) | latest |
| Our ML models | scikit-learn | latest |
| Relational DB | PostgreSQL | 15 |
| ORM / migrations | SQLAlchemy 2.x + Alembic | latest |
| Frontend | Next.js (App Router) + TypeScript | 16 |
| Styling | Tailwind CSS | latest |
| Charts | Recharts | latest |
| Local dev orchestration | docker-compose | — |
| Cloud host | AWS (EC2 + RDS + S3) | — |

**Rules for the agent:** Never substitute a library for an "equivalent." Never add a paid API. Never call an LLM from the frontend — only the backend talks to OpenRouter. Keep the LLM temperature at `0.1` for answer/verify calls (determinism harness overrides this deliberately).

---

## 2. Repository File Tree (create exactly this)

```
glassbox/
├── README.md                      # the roadmap (already written)
├── BUILD-SPEC.md                  # this file
├── docker-compose.yml             # postgres + chroma for local dev
├── .env.example                   # all env vars, documented
├── backend/
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/                   # migrations
│   ├── app/
│   │   ├── main.py                # FastAPI app + routes wiring
│   │   ├── config.py              # env loading (pydantic-settings)
│   │   ├── db.py                  # SQLAlchemy engine/session
│   │   ├── models_db.py           # ORM tables (audit log, metrics)
│   │   ├── schemas.py             # pydantic request/response models
│   │   ├── routers/
│   │   │   ├── ask.py             # POST /ask  (main pipeline)
│   │   │   ├── audit.py           # GET /audit, GET /audit/{id}
│   │   │   └── metrics.py         # GET /metrics/summary
│   │   ├── core/
│   │   │   ├── llm.py             # OpenRouter client wrapper
│   │   │   ├── retrieval.py       # embed + Chroma query
│   │   │   ├── answer_agent.py    # grounded draft generation
│   │   │   ├── verify_agent.py    # chain-of-verification
│   │   │   ├── refusal.py         # refusal/escalation logic
│   │   │   ├── trust_metrics.py   # scoring + determinism harness
│   │   │   ├── provenance.py      # write decision traces to DB
│   │   │   └── fallback.py        # offline classifier path
│   │   └── ml/
│   │       ├── train_grounding.py
│   │       ├── train_refusal.py
│   │       ├── train_fallback.py
│   │       └── artifacts/         # saved .joblib models
│   ├── corpus/
│   │   ├── ips/                   # synthetic client mandate docs (.md)
│   │   ├── factsheets/            # public fund factsheets (.md/.txt)
│   │   ├── regulations/           # public reg snippets (.md)
│   │   └── ingest.py              # chunk + embed + load into Chroma
│   ├── data/
│   │   ├── test_questions.jsonl   # eval questions + expected behavior
│   │   └── training/              # labeled data for the 3 ML models
│   └── tests/
│       └── test_acceptance.py     # per-phase acceptance checks
├── frontend/
│   ├── package.json
│   ├── app/
│   │   ├── page.tsx               # advisor chat UI
│   │   ├── dashboard/page.tsx     # governance dashboard
│   │   └── audit/[id]/page.tsx    # replay a single decision
│   ├── components/
│   │   ├── ChatPanel.tsx
│   │   ├── SourceCitations.tsx
│   │   ├── TrustBadges.tsx
│   │   └── MetricsCharts.tsx
│   └── lib/api.ts                 # backend fetch helpers
└── infra/
    └── aws-notes.md               # deploy steps (EC2/RDS/S3/IAM)
```

---

## 3. Environment Variables (`.env.example`)

```
# --- LLM ---
OPENROUTER_API_KEY=sk-or-...            # free account key
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_TEMPERATURE=0.1

# --- Vector / embeddings ---
EMBED_MODEL=BAAI/bge-small-en-v1.5
CHROMA_DIR=./chroma_store

# --- Database ---
DATABASE_URL=postgresql+psycopg://glassbox:glassbox@localhost:5432/glassbox

# --- App ---
BACKEND_PORT=8000
FRONTEND_API_BASE=http://localhost:8000
RATE_LIMIT_PER_MIN=10                    # public-demo guardrail
DETERMINISM_RUNS=5                       # N runs per query in harness

# --- AWS (prod only) ---
AWS_REGION=ap-south-1
S3_CORPUS_BUCKET=glassbox-corpus
```

---

## 4. Data Schemas (frozen)

### 4.1 IPS document (synthetic) — markdown with a YAML front-matter block
Each file in `corpus/ips/` looks like:
```
---
client_id: C001
risk_profile: moderate           # conservative | moderate | aggressive
max_single_position_pct: 25
min_liquid_within_30d_pct: 15
excluded_sectors: [tobacco, firearms, gambling]
excluded_regions: [russia]
jurisdiction: [CH, US]
---
# Investment Policy Statement — Client C001
Plain-language restatement of the rules above, one rule per sentence so it
retrieves cleanly. e.g. "No single position may exceed 25% of portfolio value."
```

### 4.2 Factsheet — plain text/markdown
```
fund_id: F100
name: Global Emerging Markets Equity Fund
asset_class: equity
region: emerging_markets
risk_level: high                 # low | medium | high
sectors: [technology, financials]
```

### 4.3 Vector chunk metadata (stored in Chroma alongside text)
```json
{ "source_id": "C001", "source_type": "ips|factsheet|regulation",
  "file": "corpus/ips/C001.md", "chunk_index": 3 }
```

### 4.4 Postgres tables (`models_db.py`)
**`decisions`** (one row per /ask call):
```
id (uuid pk) | created_at (ts) | question (text) | client_id (text, nullable)
| outcome (enum: answered|refused|fallback) | final_answer (text)
| determinism_score (float, nullable) | grounding_score (float, nullable)
| llm_model (text) | latency_ms (int)
```
**`decision_claims`** (one row per atomic claim checked):
```
id (uuid pk) | decision_id (fk) | claim_text (text)
| cited_source_id (text, nullable) | verified (bool) | kept (bool)
```
**`retrieved_chunks`** (provenance of what was fetched):
```
id (uuid pk) | decision_id (fk) | source_id | source_type | chunk_text | score (float)
```

### 4.5 Test questions (`data/test_questions.jsonl`) — one JSON per line
```json
{"q":"Can client C001 put 40% into fund F100?","client_id":"C001","expect":"refused_or_flag","reason":"violates 25% single-position limit"}
{"q":"Is fund F100 suitable for a conservative client?","client_id":"C001","expect":"answered","reason":"risk mismatch should be explained from sources"}
{"q":"What is the capital gains tax rate in Germany?","client_id":"C001","expect":"refused","reason":"no tax document in corpus"}
```

---

## 5. API Contracts (frozen)

### POST `/ask`
Request:
```json
{ "question": "string", "client_id": "C001 | null", "byo_key": "string | null" }
```
Response:
```json
{
  "decision_id": "uuid",
  "outcome": "answered | refused | fallback",
  "answer": "string | null",
  "citations": [ { "source_id": "C001", "source_type": "ips", "snippet": "..." } ],
  "refusal_reason": "string | null",
  "trust": { "grounding_score": 0.0, "determinism_score": 0.0 }
}
```

### GET `/audit?limit=50` → list of decision summaries
### GET `/audit/{decision_id}` → full replay: question, retrieved_chunks, decision_claims, final outcome
### GET `/metrics/summary` →
```json
{ "total": 0, "hallucination_rate": 0.0, "refusal_rate": 0.0,
  "avg_determinism": 0.0, "audit_completeness": 1.0 }
```

---

## 6. The Three Trained Models (exact spec)

> All scikit-learn, CPU, saved as `.joblib` in `backend/app/ml/artifacts/`. Training data lives in `backend/data/training/`. Each trainer script must: load data → build features → train → print accuracy/F1 → save artifact.

### 6.1 Grounding / hallucination scorer (`train_grounding.py`)
- **Goal:** given (answer_claim, cited_source_text), output supported probability.
- **Label data:** `grounding.jsonl` — `{"claim":"...","source":"...","label":1|0}` (1=supported). Generate ~300 rows: positives from real corpus sentences, negatives by pairing claims with unrelated sources or by mutating numbers.
- **Features:** embedding cosine similarity between claim and source + token-overlap ratio + numeric-match flag.
- **Model:** `LogisticRegression` or `RandomForestClassifier`.
- **Used in:** `trust_metrics.py` to compute per-answer grounding_score.

### 6.2 Refusal router (`train_refusal.py`)
- **Goal:** given (question, top-retrieval-score), predict answerable vs escalate.
- **Label data:** `refusal.jsonl` — `{"question":"...","top_score":0.0,"label":"answer|escalate"}`. ~200 rows; escalate examples = out-of-corpus topics (tax, legal advice) and very low retrieval scores.
- **Features:** embedding of question + max retrieval similarity + question length.
- **Model:** `LogisticRegression`.
- **Used in:** `refusal.py` as a second check alongside a retrieval-score threshold.

### 6.3 Fallback classifier (`train_fallback.py`)
- **Goal:** when OpenRouter is unreachable, return a safe structured verdict.
- **Label data:** `fallback.jsonl` — `{"question":"...","client_rule_hit":"...","verdict":"allowed|violation|escalate"}` derived from logged `decisions`.
- **Features:** question embedding + matched IPS rule flags.
- **Model:** `RandomForestClassifier`.
- **Used in:** `fallback.py`; auto-activates on LLM call failure, returns the same response JSON shape with `outcome:"fallback"`.

---

## 7. Pipeline Logic (the /ask flow, step by step)

1. Receive question (+ optional client_id).
2. **Retrieve:** embed question → Chroma top-k (k=6), filtered by client_id when present.
3. **Refusal check:** if top score < threshold (0.35) OR refusal router says escalate → return `refused` with reason; log; stop.
4. **Answer agent:** LLM drafts answer using ONLY retrieved chunks; must label each claim with its source_id.
5. **Verify agent (CoVe):** split draft into atomic claims → for each, ask LLM "is this supported by [cited chunk]? yes/no" AND run grounding scorer → drop claims that fail either.
6. If all claims dropped → `refused`. Else assemble verified answer + citations.
7. **Trust metrics:** grounding_score = mean of kept-claim scores. (Determinism score filled by the harness, not every call.)
8. **Provenance:** write `decisions` + `decision_claims` + `retrieved_chunks`.
9. On any LLM failure at steps 4–5 → **fallback path** (offline classifier), `outcome:"fallback"`.

**Determinism harness (separate endpoint/script):** run the same question `DETERMINISM_RUNS` times at temperature 0.1, compare answers (normalized text + claim-set overlap), output a 0–1 determinism_score. Optional: repeat with a second model for the comparison write-up.

---

## 8. Acceptance Tests (what "done" means per phase)

These live in `tests/test_acceptance.py` and are referenced by each phase file.

- **P1 Retrieval:** querying "single position limit" for C001 returns the IPS chunk containing the 25% rule in top-3.
- **P2 Answer+grounding:** every claim in a returned answer carries a `source_id` present in the retrieved set; no uncited claims survive.
- **P3 Verify+refusal:** the German-tax test question returns `refused`; the C001 40% question returns `refused` or a violation explanation.
- **P4 Provenance:** after an /ask, `GET /audit/{id}` returns retrieved_chunks + decision_claims and is fully reconstructable.
- **P5 Trust models:** `/metrics/summary` returns a non-null hallucination_rate computed from the grounding scorer; killing the LLM key triggers the fallback path with valid JSON.
- **P6 Determinism:** harness returns a 0–1 score; running it twice on the same question gives stable scores.
- **P7 Deploy:** public URL responds; exceeding `RATE_LIMIT_PER_MIN` returns HTTP 429 with a friendly message.

---

## 9. Guardrails for the Coding Agent (paste-in reminders)

- Build and verify **one phase at a time**; do not scaffold future phases early.
- After each phase, run the relevant acceptance test and report pass/fail before continuing.
- Never call the LLM from the frontend. Never hardcode secrets. Read all config from env.
- If a decision isn't specified here, ask, don't invent. Prefer the simplest implementation that passes the acceptance test.
- Keep functions small and typed. Add docstrings. No dead/placeholder code claiming to "do X later".
