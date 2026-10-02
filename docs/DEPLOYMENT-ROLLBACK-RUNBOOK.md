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

1. Identify the last known-good deployment artifact or commit (image tag).
2. Confirm database migrations are backward-compatible before rolling back code.
3. The backend image runs `alembic upgrade head` on start, and an older image doesn't know a newer revision, so it would fail to boot. Start the older image with `GLASSBOX_SKIP_MIGRATIONS=1` against the newer, backward-compatible schema. Avoid `alembic downgrade` in production: downgrades drop the tables and columns a migration added, which can delete reviews or thread context and break audit verification for decisions that used them.
4. Disable background jobs or manual eval runs if they depend on the new schema (`DETERMINISM_SCHEDULER_ENABLED=0` stops the nightly determinism run).
5. Roll back the backend first, then the frontend if API contracts changed.
6. Run login, advisor ask, escalation, and audit replay smoke tests, and confirm `/audit/verify` still reports the chain intact.

## Communication

- Record the failed version, rollback version, and reason.
- Capture impacted routes, tenants, and model providers.
- Document whether advisor decisions during the incident need Compliance review.
