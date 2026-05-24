# GlassBox Later Tracker

The local implementation is complete enough to run, test, demo, and extend. These
items are intentionally left for the cloud or stronger-model phase.

## Needs external services

- OpenRouter key is configured locally and `GLASSBOX_LOCAL_LLM=0` is set in `.env`.
- Product model routing is now available through `/models/health` and
  `/models/leaderboard`. The leaderboard persists eval runs/results, exposes
  `/models/eval-runs`, and gates models on outcome, citations, retrieval,
  faithfulness, golden-claim coverage, hallucination, determinism, latency, and
  category-level scores. For product-mode tests, set `GLASSBOX_LOCAL_LLM=0`, run
  a local Ollama or vLLM model, and keep free OpenRouter models disabled with
  `GLASSBOX_PRODUCTION_MODE=1`.
- Production inference requires a recent passing eval run by default
  (`REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION=1`). Run:
  `cd backend && source ../.venv/bin/activate && PYTHONPATH=. python -m scripts.run_model_eval --routes ollama:qwen2.5-coder:1.5b --limit 164 --determinism-runs 2 --print-approved-env`
  and use the printed `APPROVED_MODELS=...` value for product mode once the route
  passes.
- Re-run hosted checks after OpenRouter free-model rate limits clear. Current hosted chat completion returns HTTP 429, and the app correctly falls back to deterministic local answers.
- Verify Llama hosted mode:
  `cd backend && source ../.venv/bin/activate && GLASSBOX_LOCAL_LLM=0 LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free PYTHONPATH=. python scripts/check_openrouter.py --chat --ask`
- Verify Qwen hosted mode:
  `cd backend && source ../.venv/bin/activate && GLASSBOX_LOCAL_LLM=0 LLM_MODEL=qwen/qwen3-coder:free PYTHONPATH=. python scripts/check_openrouter.py --chat --ask`
- Keep `GLASSBOX_LOCAL_LLM=1` as the default demo mode until the hosted checks pass with a real key.
- Deploy the backend to AWS EC2 or Lambda.
- Move audit storage from local SQLite to RDS PostgreSQL.
- Upload the corpus to S3 and sync it before indexing.
- Deploy the frontend with `NEXT_PUBLIC_API_BASE` pointed at the public backend URL.

## Optional upgrades

- Re-run the deterministic browser demo after major UI/API changes:
  `cd frontend && E2E_BASE_URL=http://127.0.0.1:3001 npm run test:e2e:demo`
  Use a local backend started with `GLASSBOX_LOCAL_LLM=1 RATE_LIMIT_PER_MIN=200` for a stable demo test.
- Replace the local hash embedding fallback with `BAAI/bge-small-en-v1.5` by setting `GLASSBOX_EMBEDDING_BACKEND=sentence-transformers`.
- Replace the local file vector store with Chroma server or pgvector if the corpus grows.
- Add authentication before using any real client data.
- Add a proper dataset labeling workflow for the trust models instead of synthetic bootstrapped labels.
- Expand `backend/data/model_eval_questions.jsonl` beyond the current 164-question
  benchmark as the corpus grows. Use `backend/scripts/generate_model_eval_questions.py`
  as the repeatable baseline generator, then add human-reviewed cases manually.
- Add screenshots and a short demo video to the main README.
- Re-check the frontend dependency audit before public deployment. `npm audit --omit=dev` currently reports a moderate advisory from Next's internal PostCSS dependency with only a breaking `--force` path suggested by npm.

## Not recommended yet

- Do not fine-tune a finance LLM until the grounded/audited baseline has measured gaps.
- Do not put real financial-client data in the demo corpus.
- Do not run GPU instances on AWS for this version.
