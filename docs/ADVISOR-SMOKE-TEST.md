# Advisor Ask Smoke Test Runbook

Use this runbook before enabling a production model route for advisor traffic.

## Preconditions

- The backend is running with `GLASSBOX_PRODUCTION_MODE=1`.
- `/models/production-status` reports `product_inference_allowed=true` for the intended route.
- The frontend points at the same backend origin advisors will use.
- A test advisor account can access at least one client with IPS evidence.

## Smoke Cases

Run these through the real advisor UI, not only backend scripts:

1. Ask an answered mandate question, such as the client's single-position limit.
2. Ask a flagged allocation question that should cite the client IPS.
3. Ask an out-of-scope question that should be refused with an escalation path.
4. Open an escalation from a flagged or refused answer and confirm it appears in the review queue.
5. Open the replay link and confirm citations, retrieved evidence, model route, and latency are visible.

## Pass Criteria

- The answer is written in advisor-readable language.
- Every material claim has a visible citation.
- Refused and flagged answers expose the escalation action.
- The trust panel shows the expected production route.
- The total perceived response time is acceptable for the advisor workflow.
