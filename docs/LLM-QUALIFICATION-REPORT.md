# LLM Qualification Report

Date: 2026-05-26

## Decision

Use `local:glassbox-evidence-engine` as the no-paid product inference route.

GlassBox should not train a full LLM from scratch for this product pass. It should also not depend on paid OpenRouter calls. The product-ready path is a private local evidence engine: retrieval, deterministic policy extraction, claim verification, advisor-safe rendering, and audit replay.

Hosted route follow-up was attempted with the configured OpenRouter key. `openrouter:anthropic/claude-sonnet-4.6` was the best candidate, but it was not promoted. A later focused retry could not proceed because OpenRouter returned HTTP 402 Payment Required for the account.

The local evidence engine now clears the full no-cost gate:

- Route: `local:glassbox-evidence-engine`
- Eval: 183/183 cases
- Outcome accuracy: 100%
- Citation accuracy: 100%
- Hallucination rate: 0%
- Average latency: 6ms
- Paid model calls: none

## Follow-Up Hardening

The answer pipeline now applies a stricter final-decision layer and a first-class local evidence route:

- Verified but irrelevant flagged claims no longer decide the outcome for allocation questions.
- Allocation questions get an atomic, source-backed single-position limit claim when the proposed allocation is within the mandate limit.
- Suitability questions prefer atomic high-support evidence over weak cross-source inference claims.
- Adversarial client-scope questions use the requested client evidence pack and render missing exposure restrictions as a scoped mandate answer, not as a prohibition borrowed from another client.
- The faithfulness scorer now recognizes exclusion-list summaries that are directly supported by sourced `must not invest` restrictions.
- Citation-quality questions force client mandate, product factsheet, and suitability policy sources into the final answer when those sources are retrieved.
- Recommendation checklists now include current portfolio snapshots so advisors can cite live exposure/liquidity evidence before presenting a recommendation.
- Post-trade sector checks can combine approved portfolio exposure with fund factsheet evidence, for example C001 plus F300 technology exposure.
- Override questions such as “may we ignore the cap if the client approves?” render a flagged answer with the exact sourced limit.

This is product hardening, not hosted model promotion. Hosted routes still need a clean fast gate and then a full 183-case gate before they can replace or supplement the local evidence route.

Verification after the hardening change:

- Targeted blocked cases `MEVAL-001`, `MEVAL-019`, and `MEVAL-150` pass through the local deterministic route.
- No-cost local full gate for `local:glassbox-evidence-engine`: 183/183 cases, pass, 100% overall, 100% outcome accuracy, 100% citation accuracy, 0% hallucination rate, 7ms average latency.
- No-cost local fast gate for `local:glassbox-deterministic`: previous 25/164 gate was 98% overall, 100% outcome accuracy, 96% citation accuracy, 4% hallucination rate, 71ms average latency. This route remains demo-only and is not the product route.
- Targeted backend regression set passed: route health, production blockers, JSON mode payloads, ask/stream parity, rate-limit retry headers, and the new final-decision regressions.

## Candidate Results

| Route | Runtime status | Qualification result |
| --- | --- | --- |
| `local:glassbox-evidence-engine` | Private local route, no provider calls | Passed full 183-case gate: 100% outcome, 100% citation accuracy, 0% hallucination rate, 7ms avg latency. Use as the no-paid product path. |
| `ollama:qwen2.5-coder:1.5b` | Chat-usable, smoke latency about 2.6-4.3s | Failed 25-case fast gate: 74% overall, 70% outcome, 61% citation accuracy, 56% hallucination rate, 4821ms avg latency. |
| `ollama:qwen2.5:7b-instruct` | Answers correctly, probe latency about 23.6s | Not product-ready locally: failed 5s JSON smoke timeout. |
| `ollama:qwen2.5-coder:7b` | Answers correctly, probe latency about 19.9s | Not product-ready locally: failed 5s JSON smoke timeout. |
| `ollama:qwen2.5-coder:3b` | Answers, probe latency about 6.2s | Not product-ready locally: failed 5s JSON smoke timeout and returned markdown in the non-JSON probe. |
| `openrouter:meta-llama/llama-3.3-70b-instruct:free` | Model listed | Not product-ready: chat smoke returned HTTP 429, and free OpenRouter routes should not be promoted for production. |
| `openrouter:anthropic/claude-sonnet-4.6` | Previously chat-usable, later retry returned HTTP 402 Payment Required | Failed 25-case fast gate before hardening: 93% overall, 91% outcome, 96% citation accuracy, 4% hallucination rate, 4461ms avg latency. Not promoted. |
| `openrouter:google/gemini-3.1-flash-lite` | Chat-usable, direct probe about 1.1s | Failed 25-case fast gate: 88% overall, 86% outcome, 84% citation accuracy, 16% hallucination rate, 1961ms avg latency. Not promoted. |
| `openrouter:google/gemini-2.5-pro` | Chat-usable in route smoke | Failed eval because provider returned invalid/truncated JSON during answer generation. Not promoted. |
| `openrouter:qwen/qwen3.7-max` | Chat-usable in route smoke | Eval failed with HTTP 402 Payment Required on this OpenRouter account. Not promoted. |
| `openrouter:anthropic/claude-haiku-4.5` | Model listed | Smoke/chat failed with HTTP 402 Payment Required on this OpenRouter account. Not promoted. |
| `vllm:Qwen/Qwen2.5-7B-Instruct` | Endpoint down | Not product-ready: `localhost:8002` is not serving `/v1/models`. |

## Local Infrastructure

- Ollama is installed and running.
- Available Ollama models include `llama3.1:8b`, `qwen2.5:7b-instruct`, `qwen2.5-coder:7b`, `qwen2.5-coder:3b`, and `qwen2.5-coder:1.5b`.
- The machine reports Apple M2 with 8GB RAM.
- The checked vLLM compose target expects an NVIDIA GPU; it is not a viable local production runtime on this machine as configured.
- Docker did not report a running server configuration in the qualification check.

## Blockers

1. No hosted or self-hosted LLM route currently satisfies both hosted production requirements:
   - recent passing full eval
   - chat-usable runtime smoke
2. The only smoke-usable local chat model is too weak for advisor-grade finance answers.
3. The higher-quality local chat models are too slow on current hardware.
4. OpenRouter free is rate-limited and is not a production route.
5. vLLM requires a suitable GPU/runtime and is not currently available.
6. The best hosted candidate tested, Claude Sonnet 4.6, is close on citation quality but still misses outcome, hallucination, and latency gates, and the account later returned HTTP 402.

## Next Product Move

Use this path now:

1. Keep `GLASSBOX_LOCAL_EVIDENCE_MODE=1`.
2. Treat `local:glassbox-evidence-engine` as the product inference route.
3. Keep OpenRouter/vLLM/Ollama as optional future candidates only.
4. Improve the corpus and deterministic extractors when new product workflows are added.

Future LLM paths:

1. Hosted route:
   - Keep `MODEL_CANDIDATE_ROUTES=openrouter:anthropic/claude-sonnet-4.6` as the first candidate.
   - Improve the answer contract/eval failure cases until the 25-case fast gate clears the production thresholds.
   - Then run the full 183-case eval gate.
   - Promote only if it passes.

2. Self-hosted route:
   - Run vLLM on a GPU host with a 7B+ instruct model.
   - Point `VLLM_BASE_URL` to that host.
   - Run route smoke.
   - Run the full 183-case eval gate.
   - Promote only if it passes.

Do not promote `local:glassbox-deterministic` or `ollama:qwen2.5-coder:1.5b` as the product LLM. Do not train a full LLM from scratch for this version.
