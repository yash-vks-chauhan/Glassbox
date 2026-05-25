# Escalation Runbook

Use this runbook when an advisor opens a flagged or refused GlassBox decision for Compliance review.

## When To Escalate

- The answer is `flagged` and the advisor wants to request an exception.
- The answer is `refused` because required evidence is missing or weak.
- The advisor believes the retrieved evidence is incomplete.
- A client action is blocked by an IPS, factsheet, or suitability constraint.

## Review Steps

1. Open the escalation from the review queue.
2. Open the decision replay and confirm the question, client, outcome, citations, and model route.
3. Check that every material claim is supported by the cited document text.
4. Confirm any numeric limits, such as allocation caps or liquidity floors, against the IPS.
5. Record the Compliance decision before marking the escalation resolved.

## Resolution Criteria

- `resolved`: Compliance has reviewed and documented the decision.
- `in_review`: Compliance owns the case and is still investigating.
- `cancelled`: The advisor no longer needs review or opened the escalation by mistake.

Escalations should not be closed only because the UI action succeeded. The reviewer should leave enough context for an audit replay to explain why the case was resolved.
