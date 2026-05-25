# Tenant Onboarding Checklist

Use this checklist when adding a new tenant to GlassBox.

## Setup

- Create the tenant record and slug.
- Create the initial owner account and require MFA enrollment.
- Confirm advisor, compliance, admin, and owner roles are assigned intentionally.
- Confirm invite links expire and are sent through the intended channel.

## Corpus

- Place tenant IPS documents under the tenant-scoped corpus path.
- Confirm shared factsheets and regulations are available to the tenant.
- Run corpus ingestion after adding or updating documents.
- Ask one mandate question per seeded client and verify tenant-specific citations.

## Access Verification

- Advisor users can only see their tenant data.
- Compliance users can see tenant escalations and audit replay.
- Admin users can manage users and model settings.
- Cross-tenant client IDs return no data.

## Sign-Off

Record the tenant ID, seeded users, corpus version, and smoke-test results before enabling advisor traffic.
