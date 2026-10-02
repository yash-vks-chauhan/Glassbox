# GlassBox: what's left

The product runs end to end locally, in Docker and on AWS, with CI on
every pull request. What remains needs real data, money, or a decision.

## The deployment

It runs on one server ([infra/single-server](infra/single-server/README.md)).
Next steps, when they're worth paying for:

- A domain name instead of the `sslip.io` address.
- The managed setup in [infra/aws-notes.md](infra/aws-notes.md) (ECS
  Fargate, RDS, an ALB) once it needs to survive the loss of a server. A
  single instance has no redundancy; daily snapshots are the backup.
- AWS Budgets alerts on the account, and an IAM admin user for deploying
  instead of the root sign-in.
- Optionally sync the corpus from S3 instead of baking it into the image, if
  documents should change without a rebuild.
- Infrastructure as code (Terraform or CDK) for what is now a set of CLI
  commands.

## Needs a hosted or self-hosted model

The local evidence engine is the product path and needs no model. To add a
model that writes advisor-facing text:

- Run a candidate (`docker compose -f docker-compose.vllm.yml up -d`, Ollama,
  or a paid OpenRouter model), then the full evaluation gate:
  `PYTHONPATH=. python -m scripts.run_model_eval --routes <route> --gate full --determinism-runs 2`
  from `backend/`, and promote it with `scripts/promote_model.py` only if it
  passes. [docs/PRODUCTION-LLM.md](docs/PRODUCTION-LLM.md) has the rules.
- Free OpenRouter models were rate-limited (HTTP 429) when last checked, and
  stay disabled in production mode.

## Needs real data and reviewers

- The benchmark (183 questions) and the corpus are synthetic and were
  written alongside the engine. Real mandates and a firm's own reviewers are
  the only way to learn how it does on real documents.
- The grounding scorer was trained on bootstrapped labels. Reviewer claim
  labels are now collected (`scripts/export_review_labels.py`); retrain on
  them once there are enough.
- Never put real client data into the demo corpus.

## Worth doing later

- pgvector instead of the NumPy index if the corpus grows past a few
  thousand passages.
- Neural embeddings (`requirements-embeddings.txt`,
  `GLASSBOX_EMBEDDING_BACKEND=sentence-transformers`); re-run the benchmark
  before switching.
- SSO (Okta, Entra ID) and WebAuthn / passkeys; MFA is TOTP today.
- A demo video next to the screenshots in `docs/screenshots/`.

## Not recommended

- Fine-tuning a finance LLM before the grounded, audited baseline shows a
  measured gap that fine-tuning would close.
- GPU instances on AWS for this version.
