# Model Evaluation Runbook

Use this runbook when testing a model route before it can serve production advisor requests.

## Fast Gate

Use the fast gate during local development and model smoke testing:

```bash
cd backend
PYTHONPATH=. python scripts/run_model_eval.py \
  --routes "local:glassbox-deterministic" \
  --gate fast \
  --determinism-runs 2 \
  --no-persist
```

The fast gate is not enough for production approval. It is a short signal that the route and prompt profile are not obviously broken.

## Full Gate

Use the full gate before promotion:

```bash
cd backend
PYTHONPATH=. python scripts/run_model_eval.py \
  --routes "vllm:Qwen/Qwen2.5-7B-Instruct" \
  --gate full \
  --determinism-runs 2 \
  --fail-on-no-production-ready
```

A model should not be added to `APPROVED_MODELS` unless the latest full run passes the production thresholds.

## Review Checklist

- Confirm the evaluated route matches the deployment route exactly.
- Review failure buckets for unsupported citation, wrong outcome, latency breach, prompt-injection failure, and numeric compliance error.
- Confirm p95 latency is within the advisor response target.
- Confirm refusal correctness is high enough for missing evidence and out-of-scope questions.
- Keep the run ID in the deployment notes so the model decision can be audited later.
