# Production LLM Route

GlassBox product inference is grounded-generative: the model can write the advisor-facing answer, but `/ask` must use retrieved evidence and a model route with a recent passing full eval.

## Production Rule

Set production mode only when at least one configured candidate route has passed the full eval gate:

```bash
GLASSBOX_PRODUCTION_MODE=1
GLASSBOX_LOCAL_LLM=0
REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION=1
MODEL_CANDIDATE_ROUTES=vllm:Qwen/Qwen2.5-7B-Instruct,openrouter:<paid-model-id>
APPROVED_MODELS=vllm:Qwen/Qwen2.5-7B-Instruct
```

If no candidate route is approved, `/ask` returns `503` and does not fall back to the deterministic demo engine.

## Self-Hosted vLLM

Run a production candidate route:

```bash
docker compose -f docker-compose.vllm.yml up -d
cd backend
PYTHONPATH=. python scripts/check_model_route.py --route "vllm:Qwen/Qwen2.5-7B-Instruct"
```

For real production, pin `VLLM_IMAGE` to the exact image version used in staging.

## Approval Flow

Run the full benchmark and persist results:

```bash
cd backend
PYTHONPATH=. python scripts/run_model_eval.py \
  --routes "vllm:Qwen/Qwen2.5-7B-Instruct" \
  --gate full \
  --determinism-runs 2 \
  --fail-on-no-production-ready
```

Promote only after the latest full eval passes:

```bash
PYTHONPATH=. python scripts/promote_model.py \
  --route "vllm:Qwen/Qwen2.5-7B-Instruct" \
  --write-env-file ../.env
```

The promotion script does not approve a model by itself. It only writes `APPROVED_MODELS` when the database already has a passing full eval for that route.

## Pre-Deployment Checklist

Before enabling a route for advisors, record these checks in the release note:

- The latest full eval run used the same model route and prompt profile that will run in production.
- The route passed outcome accuracy, citation support, refusal correctness, numeric compliance, prompt-injection resistance, and p95 latency thresholds.
- `/models/production-status` reports `product_inference_allowed=true` for the intended route.
- `/ask/stream` was smoke-tested with at least one answered, flagged, and refused advisor question.
- The advisor UI was smoke-tested against the approved route, not only backend scripts.
- The deterministic fallback remains disabled for product inference and is documented as demo or outage-only.
