# BYO Key Operations Runbook

Use this runbook for advisor or tenant-provided model provider keys.

## Enrollment

- Save keys through the BYO key settings flow, not through `/ask` payloads.
- Confirm the backend stores only encrypted key material.
- Confirm the UI displays provider and last-four metadata only.
- Confirm deleting a key removes it from future inference requests.

## Rotation

1. Add the replacement key for the same provider.
2. Run a model health check.
3. Run a small advisor ask smoke test.
4. Remove the previous key.
5. Record the rotation time and provider.

## Incident Handling

If a key may be exposed, remove it immediately, rotate at the provider, and review audit logs for model calls made during the exposure window.
