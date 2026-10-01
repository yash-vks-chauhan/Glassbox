# Production Inference Route

GlassBox now has two inference paths:

1. **Private local evidence mode**: no paid model, no hosted LLM, no GPU. `/ask` answers from retrieved sources, deterministic policy checks, claim verification, and audit replay.
2. **Hosted/self-hosted LLM route**: optional future path where a model writes advisor-facing text but must pass runtime and eval gates first.

The default product path is private local evidence mode:

```bash
GLASSBOX_LOCAL_EVIDENCE_MODE=1
GLASSBOX_LOCAL_LLM=1
GLASSBOX_PRODUCTION_MODE=1
APPROVED_MODELS=
```

In this mode, `/ask` records `local:glassbox-evidence-engine` as the model route. It does not call OpenRouter, Ollama, or vLLM for answer generation.

## Local Evidence Gate

The local evidence route must still be evaluated, but it does not require `APPROVED_MODELS` promotion because it is not a chat provider route:

```bash
cd backend
PYTHONPATH=. python scripts/run_model_eval.py \
  --routes "local:glassbox-evidence-engine" \
  --gate full \
  --determinism-runs 2 \
  --no-persist
```

Latest no-cost qualification on 2026-05-26:

- 183/183 eval cases
- 100% outcome accuracy
- 100% citation accuracy
- 0% hallucination rate
- 7ms average latency

## Hosted Model Rule

Use this only when GlassBox has a paid hosted route or a real self-hosted runtime. A hosted model route is product-ready only when both checks pass:

1. **Approval:** the latest full eval for the route passes production thresholds and freshness.
2. **Runtime:** the configured provider completes the cached JSON chat smoke test.

If either check fails in production mode, `/ask` returns `503` instead of falling back to the deterministic demo engine.

## Hosted Production Rule

For hosted/self-hosted model routes, set production mode only when at least one configured candidate route has passed the full eval gate:

```bash
GLASSBOX_LOCAL_EVIDENCE_MODE=0
GLASSBOX_PRODUCTION_MODE=1
GLASSBOX_LOCAL_LLM=0
REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION=1
MODEL_CANDIDATE_ROUTES=vllm:Qwen/Qwen2.5-7B-Instruct,openrouter:<paid-model-id>
APPROVED_MODELS=vllm:Qwen/Qwen2.5-7B-Instruct
```

If no candidate route is approved, or the approved route is not chat-usable, `/ask` returns `503` and does not fall back to the deterministic demo engine.

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
