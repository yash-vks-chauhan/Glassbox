# Release Checklist

Use this checklist before merging or deploying a GlassBox release.

CI runs the automated parts of this list on every pull request; a release needs it green on the release commit.

## Backend

- Run the backend test suite on SQLite and on Postgres (`GLASSBOX_TEST_DATABASE_URL`), plus `ruff check .` and `pip-audit -r requirements.txt`.
- Confirm migrations apply cleanly from the previous release.
- Confirm tenant-scoped corpus ingestion succeeds.
- Confirm `/health`, `/models/production-status`, and `/audit/verify` respond as expected.

## Frontend

- Run `npm run lint`, `npm run typecheck`, `npm run build` and `npm audit --omit=dev`.
- Run the browser e2e suite (`npm run test:e2e`): login and MFA, first-run setup, invitations, advisor ask, threads, escalation and review, audit export, Admin access, and silent refresh.
- Confirm the frontend API base matches the deployed backend origin (`NEXT_PUBLIC_API_BASE` is compiled into the frontend image).
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
