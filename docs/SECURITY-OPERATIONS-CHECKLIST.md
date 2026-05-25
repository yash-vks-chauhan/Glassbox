# Security Operations Checklist

Use this checklist before running GlassBox with real advisor or client data.

## Required Configuration

- `APP_ENCRYPTION_KEY` is set to a production secret and is not checked into the repository.
- `JWT_SECRET_KEY` is set to a production secret with enough entropy.
- `FRONTEND_ORIGIN` matches the deployed frontend origin exactly.
- Rate limits are configured for auth, ask, and default API traffic.
- `GLASSBOX_LOCAL_LLM=0` is set for production advisor traffic.

## Access Controls

- The first owner account is enrolled in MFA.
- Admin access is limited to owner/admin roles.
- Compliance users can access escalations and audit review.
- Advisor users cannot access Admin pages or tenant-wide review controls.
- Inactive users have sessions revoked.

## Audit And Evidence

- Audit verification passes before deployment.
- Escalation actions create audit events.
- BYO model keys are encrypted at rest.
- Decision replay includes retrieved chunks, citations, model route, and timing metadata.

## Incident Checks

- Confirm logs do not print access tokens, refresh tokens, BYO keys, or raw secrets.
- Confirm lockout and rate-limit events are visible enough for operations review.
- Confirm password reset and invite emails are delivered through the intended channel.
