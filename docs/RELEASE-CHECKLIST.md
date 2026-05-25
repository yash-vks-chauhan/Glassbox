# Release Checklist

Use this checklist before merging or deploying a GlassBox release.

## Backend

- Run the backend test suite.
- Confirm migrations apply cleanly from the previous release.
- Confirm tenant-scoped corpus ingestion succeeds.
- Confirm `/health`, `/models/production-status`, and `/audit/verify` respond as expected.

## Frontend

- Run TypeScript validation.
- Run the browser e2e flow for login, advisor ask, escalation, Admin access, and silent refresh.
- Confirm the frontend API base matches the deployed backend origin.
- Confirm refused and flagged answers expose the escalation action.

## LLM And Evaluation

- Record the active model route and prompt profile.
- Attach the latest full eval run ID when production inference is enabled.
- Confirm deterministic fallback is disabled for production advisor traffic.
- Confirm advisor-facing answers include citations and a clear next action.

## Release Notes

Include:

- Summary of user-facing changes.
- Migration notes.
- Known limitations.
- Rollback plan.
- Verification commands or e2e run links.
