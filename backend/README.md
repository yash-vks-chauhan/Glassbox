# GlassBox backend

FastAPI app, Alembic migrations, the retrieval corpus, the trained trust
models, and the scripts that evaluate them. Commands below run from
`backend/` with the virtualenv at the repo root (`../.venv`).

## Set up and run

```bash
python3.12 -m venv ../.venv
../.venv/bin/pip install -r requirements-dev.txt
cp ../.env.example ../.env       # settings are read from the repo root
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

- `requirements.txt` is the runtime; `requirements-dev.txt` adds ruff,
  pytest and pip-audit; `requirements-embeddings.txt` adds
  sentence-transformers (and PyTorch) for
  `GLASSBOX_EMBEDDING_BACKEND=sentence-transformers`. The default hash
  embeddings need none of it.
- The database is `DATABASE_URL`: SQLite (`backend/glassbox_local.db`) by
  default, or `postgresql+psycopg://user:pass@host:5432/glassbox`. Postgres
  gets its schema from `../.venv/bin/alembic upgrade head`; on SQLite the app
  also creates missing tables at startup. Startup and migrations hold a
  schema lock, so several workers or servers can start at once.
- The retrieval index is built from `corpus/` on first use (or with
  `PYTHONPATH=. ../.venv/bin/python -m corpus.ingest`) into `CHROMA_DIR`.
- The first owner of a workspace is created at `/setup` in the web app,
  which needs `BOOTSTRAP_SETUP_KEY` set.

With `GLASSBOX_LOCAL_EVIDENCE_MODE=1` (the default in `.env.example`) `/ask`
answers through the local evidence engine: retrieval, deterministic policy
checks, claim verification and audit replay, with no model provider and no
API key. `GLASSBOX_LOCAL_LLM=1` is the older deterministic demo route, kept as
a fallback.

## Test

```bash
../.venv/bin/ruff check .
../.venv/bin/pytest                      # SQLite
GLASSBOX_TEST_DATABASE_URL=postgresql+psycopg://glassbox:glassbox@localhost:5432/glassbox_test \
  ../.venv/bin/pytest                    # Postgres: an empty database whose name contains "test"
../.venv/bin/pip-audit -r requirements.txt
```

The suite builds a throwaway database (through the real migration chain),
index and mail directory, and ignores `.env`, so it can't touch your local
data, send real email or call a hosted model. A few tests only run on
Postgres (concurrent migrations and boots, the Postgres schema check).

## Evaluate the answer engine

```bash
PYTHONPATH=. ../.venv/bin/python -m scripts.run_model_eval \
  --routes local:glassbox-evidence-engine --gate full --determinism-runs 2 --no-persist
```

Scores the 183-question benchmark (`data/model_eval_questions.jsonl`) for
outcome, citations, retrieval recall, faithfulness, hallucination,
determinism, refusals, numeric compliance, prompt injection and latency. Add
`--json` for the full report, or drop `--no-persist` to store the run (the
admin page shows stored runs).

## Hosted or self-hosted models (optional)

A hosted route (OpenRouter, Ollama, vLLM) is only used in production after
its latest full evaluation passes and it is promoted into `APPROVED_MODELS`.
See [../docs/PRODUCTION-LLM.md](../docs/PRODUCTION-LLM.md). To check that a
route is reachable:

```bash
PYTHONPATH=. ../.venv/bin/python scripts/check_model_route.py --route "ollama:qwen2.5-coder:1.5b"
PYTHONPATH=. ../.venv/bin/python -m scripts.check_openrouter --chat   # needs OPENROUTER_API_KEY
```

## Scripts

| Script | What it does |
|---|---|
| `scripts/init_secrets.py` | Generates JWT, encryption and cookie secrets as env lines |
| `scripts/run_model_eval.py` | The evaluation gate above |
| `scripts/promote_model.py` | Writes `APPROVED_MODELS` for a route whose latest full eval passed |
| `scripts/run_determinism.py` | Runs the determinism harness now, or the schedules that are due (`--due`, for cron) |
| `scripts/export_review_labels.py` | Exports reviewer claim labels as training data for the grounding scorer |
| `scripts/encrypt_mfa_secrets.py` | Encrypts MFA secrets stored before encryption at rest |
| `scripts/generate_model_eval_questions.py` | Regenerates the baseline benchmark questions |
| `scripts/seed_phase_f_e2e.py` | Seeds the accounts the Playwright suite signs in with |

The trust models in `app/ml/artifacts/` are retrained with
`python -m app.ml.train_grounding`, `train_refusal` and `train_fallback`
(after `python -m app.ml.generate_training_data`). They are scikit-learn
pickles, so keep scikit-learn on the 1.8 line that wrote them.
