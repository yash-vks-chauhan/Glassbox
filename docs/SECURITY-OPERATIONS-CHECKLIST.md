# Security Operations Checklist

Use this checklist before running GlassBox with real advisor or client data.

## Required Configuration

- `GLASSBOX_PRODUCTION_MODE=1`. The API then refuses to start while `JWT_SIGNING_KEY`, `APP_ENCRYPTION_KEY` or `COOKIE_SECRET` still has its development default; generate them with `backend/scripts/init_secrets.py` and keep them out of the repository (Secrets Manager or similar).
- The answer route is deliberate: `GLASSBOX_LOCAL_EVIDENCE_MODE=1` for the local evidence engine (the default product path), or `GLASSBOX_LOCAL_LLM=0` with an approved hosted route (see [PRODUCTION-LLM.md](PRODUCTION-LLM.md)).
- `FRONTEND_ORIGIN` matches the deployed frontend origin exactly, and `REFRESH_COOKIE_SECURE=1` behind HTTPS.
- Behind a load balancer, `FORWARDED_ALLOW_IPS` is set to its address range, so rate limits and the security log see client IPs rather than the balancer's.
- Rate limits are configured for auth, ask, and default API traffic.
- `BOOTSTRAP_SETUP_KEY` is unset once each workspace has its first owner.

## Access Controls

- The first owner account is enrolled in MFA (first-owner setup at `/setup` requires it).
- Admin access is limited to owner/admin roles.
- Compliance users can access escalations and audit review.
- Advisor users cannot access Admin pages or tenant-wide review controls.
- Inactive users have sessions revoked.

## Audit And Evidence

- Audit verification passes before deployment.
- Escalation actions create audit events.
- BYO model keys and MFA secrets are encrypted at rest; BYO keys stay admin/owner-only unless `ALLOW_ADVISOR_BYO_KEYS=1` is intended.
- Decision replay includes retrieved chunks, citations, model route, and timing metadata.

## Incident Checks

- Confirm logs do not print access tokens, refresh tokens, BYO keys, or raw secrets.
- Confirm lockout and rate-limit events are visible enough for operations review.
- Confirm password reset and invite emails are delivered through the intended channel.
