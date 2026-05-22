# GlassBox Backend

## Local run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m corpus.ingest
python -m app.ml.generate_training_data
python -m app.ml.train_grounding
python -m app.ml.train_refusal
python -m app.ml.train_fallback
uvicorn app.main:app --reload --port 8000
```

The backend works without an OpenRouter key by using the deterministic local LLM path
(`GLASSBOX_LOCAL_LLM=1`). Set `GLASSBOX_LOCAL_LLM=0` plus `OPENROUTER_API_KEY`
to use the real hosted model, or leave local mode off without a key to exercise the
offline fallback classifier.

## Useful checks

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Can client C001 put 40% into fund F100?","client_id":"C001"}'
pytest
```

## Check free model wiring

```bash
python -m scripts.check_openrouter
```

This checks whether OpenRouter's model list is reachable and whether the configured
`LLM_MODEL` exists. To make a real hosted-model generation call, create `.env.local`
in the repo root:

```bash
OPENROUTER_API_KEY=sk-or-...
GLASSBOX_LOCAL_LLM=0
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
```

Then run:

```bash
python -m scripts.check_openrouter --chat
```
