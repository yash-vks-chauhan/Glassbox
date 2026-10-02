# Tenant Onboarding Checklist

Use this checklist when adding a new tenant to GlassBox.

## Setup

- Create the workspace and its first owner at `/setup` (the API needs `BOOTSTRAP_SETUP_KEY`; MFA enrolment is part of setup). Unset the key afterwards.
- Create the workspace's clients (Clients → New client), with codes matching the IPS files.
- Confirm advisor, compliance, admin, and owner roles are assigned intentionally.
- Confirm invite links expire and are sent through the intended channel.

## Corpus

- Place tenant IPS documents under `backend/corpus/tenants/<tenant_id>/ips/` and portfolio snapshots under `backend/corpus/tenants/<tenant_id>/portfolio/`.
- Confirm shared factsheets and regulations are available to the tenant (the Library page lists what the tenant can cite).
- Re-index after adding or updating documents: `python -m corpus.ingest` locally, or rebuild the backend image, which builds the index.
- Ask one mandate question per seeded client and verify tenant-specific citations.

## Access Verification

- Advisor users can only see their tenant data.
- Compliance users can see tenant escalations and audit replay.
- Admin users can manage users and model settings.
- Cross-tenant client IDs return no data.

## Sign-Off

Record the tenant ID, seeded users, corpus version, and smoke-test results before enabling advisor traffic.
