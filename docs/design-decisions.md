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

## Local deterministic mode

The local implementation includes `GLASSBOX_LOCAL_LLM=1`, a deterministic offline
LLM substitute. This lets the project run on a MacBook without paid APIs or rate
limits. Turning `GLASSBOX_LOCAL_LLM=0` makes the backend use OpenRouter, and if no
key is available the offline fallback classifier path is exercised.

## Trust models are small on purpose

The custom models are scikit-learn classifiers for grounding, refusal routing, and
fallback verdicts. This is a better student project choice than pretending to train
a finance LLM because the models are cheap to train, inspectable, and directly tied
to measurable product risk.

## Audit first

Every answer, refusal, and fallback stores retrieved chunks, claim outcomes, final
answer, model metadata, latency, and trust scores. The replay endpoint is the main
evidence that GlassBox is built for regulated workflows rather than casual chat.
