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

## The audit record is append-only

A decision is never edited after it is written. Reviews, claim labels and
corrections go into their own tables (`decision_reviews`, `claim_labels`,
`decision_corrections`) and are shown next to the original, and the database
refuses `DELETE` (and on Postgres `TRUNCATE`) on the audit tables. A
regulator asking "what did the system tell the advisor?" gets the answer as
it was, plus everything that happened to it afterwards.

## One hash chain per tenant

Each decision's hash covers its content, its claims and its retrieved
passages, plus the previous decision's hash, so editing any stored row
breaks verification from that point on. Chains are per tenant so that one
tenant's verification never depends on rows it can't see. Appends to a chain
are serialised (an advisory lock on Postgres, the single-writer lock on
SQLite) and stamped while the lock is held, so concurrent questions can't
fork the chain into a false tamper alarm. Timestamps are hashed as UTC
instants. The startup backfill only links rows that have no hash yet; it
never re-hashes a row, because a row whose content no longer matches its
hash is exactly what verification has to report.

## Follow-ups are rewritten, and the rewrite is logged

"What about F200?" can't be answered on its own. Within a thread, a
follow-up is rewritten into a standalone question by swapping the new fund
or percentage into the previous question, with plain pattern rules rather
than a model call (so the same thread always resolves the same way), and
retrieval runs on that. The
rewritten question is stored with the decision, shown under the advisor's
question ("Answered as: …") and included in the hash, so a replay shows what
was actually answered, not just what was typed.

## Reviews are four-eyes, and they teach the scorer

The person who asked a question can't review its decision. Reviewers mark
each claim as supported or not, and those labels are exported as training
data for the grounding scorer. Human oversight then improves the automated
check instead of only auditing it.

## Measuring determinism doesn't touch the audit log

The determinism harness re-asks a sample of recent questions several times
and scores how much the answers drift. Those repeat answers are measurement,
not advice, so they are stored as harness runs, never as decisions; the
audit log holds only what advisors were actually told. Nightly runs are
claimed by inserting a (tenant, day) row, so any number of servers produce
one run per tenant per day.

## Migrations are the schema, on both databases

Postgres gets its schema only from Alembic, so the test suite builds its
database through the real migration chain and runs on SQLite and on
Postgres in CI, including a check that a migrated database matches the
models. Migrations and boot-time initialisation hold one schema lock, so
replicas starting together take turns instead of racing on DDL.

## Light dependencies by default

Retrieval uses a small NumPy index and hash embeddings. They need no GPU,
no model download and no vector database, and the benchmark passes with
them. Neural embeddings (`BAAI/bge-small-en-v1.5`) are one optional
requirements file away; installing them by default would put PyTorch in
every image for no measured gain.
