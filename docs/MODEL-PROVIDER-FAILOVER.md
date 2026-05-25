# Model Provider Failover Runbook

Use this runbook when a configured model provider is slow, unhealthy, or unavailable.

## Detection

- `/models/health` reports the provider unhealthy.
- Ask latency breaches the p95 target.
- Streaming requests return errors before the final event.
- Eval or smoke tests show provider-specific failures.

## Response

1. Confirm whether the active route has a recent passing full eval.
2. Check the next candidate route health and approval state.
3. Do not route production traffic to an unapproved model.
4. If no approved route is healthy, block product inference instead of silently using demo fallback.
5. Record the provider, route, failure mode, and advisor impact.

## Recovery

Run health checks, a fast eval, and advisor UI smoke tests before restoring the provider to candidate order.
