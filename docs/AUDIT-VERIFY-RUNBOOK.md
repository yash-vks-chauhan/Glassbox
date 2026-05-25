# Audit Verification Runbook

Use this runbook to verify GlassBox decision audit integrity.

## When To Run

- Before a release.
- After restoring from backup.
- After a migration touching decision, claim, escalation, or audit tables.
- During Compliance review of an incident.

## Steps

1. Sign in as an admin or owner.
2. Open the Admin audit verification card.
3. Run `/audit/verify` from the backend if the UI is unavailable.
4. Confirm the verified count matches the expected decision count.
5. If verification fails, record the first broken decision ID and stop deployment.

## Failure Handling

- Do not delete or rewrite audit rows to make verification pass.
- Preserve the database snapshot for investigation.
- Compare the first broken decision against deployment and migration logs.
- Escalate to engineering and Compliance before resuming advisor traffic.
