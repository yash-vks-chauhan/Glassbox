# Deployment Rollback Runbook

Use this runbook when a GlassBox deployment needs to be rolled back or production model inference needs to be disabled.

## Immediate Model Rollback

If advisor answers are slow, unsupported, or failing eval expectations:

1. Remove the route from `APPROVED_MODELS`.
2. Set `REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION=1`.
3. Confirm `/models/production-status` reports production inference as blocked.
4. Confirm `/ask` returns a controlled `503` instead of falling back silently.
5. Keep existing audit and escalation records unchanged.

## Application Rollback

For application regressions:

1. Identify the last known-good deployment artifact or commit.
2. Confirm database migrations are backward-compatible before rolling back code.
3. Disable background jobs or manual eval runs if they depend on the new schema.
4. Roll back the backend first, then the frontend if API contracts changed.
5. Run login, advisor ask, escalation, and audit replay smoke tests.

## Communication

- Record the failed version, rollback version, and reason.
- Capture impacted routes, tenants, and model providers.
- Document whether advisor decisions during the incident need Compliance review.
