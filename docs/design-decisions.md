# GlassBox Design Decisions

## No full LLM training

GlassBox does not train a language model from scratch. The project goal is not to
build a larger language model; it is to build a governance layer around model
outputs. Training a full LLM would be expensive, slow, and unnecessary for the
portfolio signal this project is meant to show.

## No finance fine-tuning for the first version

Fine-tuning would push financial knowledge into model weights. That makes answers
harder to audit because the system can appear to know something without showing the
source document. GlassBox keeps the language model generic and forces answers
through retrieval, citations, claim verification, and refusal logic.

## Private local evidence mode

The product path is `GLASSBOX_LOCAL_EVIDENCE_MODE=1`. It is not a pretend LLM and
not a fine-tuned model. It answers from retrieved IPS, factsheet, and regulatory
snippets using deterministic policy extraction, claim verification, advisor-safe
rendering, and audit replay.

The older `GLASSBOX_LOCAL_LLM=1` route remains a demo/fallback substitute. It is
useful for outage handling and compatibility tests, but it is not the primary
product inference route.

## Trust models are small on purpose

The custom models are scikit-learn classifiers for grounding, refusal routing, and
fallback verdicts. This is a better student project choice than pretending to train
a finance LLM because the models are cheap to train, inspectable, and directly tied
to measurable product risk.

## Audit first

Every answer, refusal, and fallback stores retrieved chunks, claim outcomes, final
answer, model metadata, latency, and trust scores. The replay endpoint is the main
evidence that GlassBox is built for regulated workflows rather than casual chat.
