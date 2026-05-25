# Retrieval Quality Checklist

Use this checklist when changing corpus ingestion, chunking, retrieval, or evidence packaging.

## Coverage

- IPS questions retrieve the matching client IPS.
- Fund questions retrieve the matching factsheet.
- Suitability questions retrieve IPS, factsheet, and suitability guidance when available.
- Out-of-scope questions refuse instead of inventing unsupported facts.

## Evidence Pack Review

- Source IDs are stable and human-readable.
- Duplicate chunks are removed before generation.
- Chunk metadata includes source type, source version, index, score, and selection reason.
- Citations in the final answer map to the displayed evidence.

## Regression Checks

Run representative answered, flagged, refused, and prompt-injection cases after retrieval changes. Review missing-source and unsupported-citation failures before promotion.
