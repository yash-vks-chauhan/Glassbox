# GlassBox AWS Deployment Notes

This repo is fully runnable locally. AWS work is intentionally isolated here so the
local project does not require credentials or spend.

## Billing guardrails

1. Create AWS Budgets alerts at `$20`, `$50`, and `$100`.
2. Do not create GPU instances for this project.
3. Stop or terminate idle EC2 instances after demos.
4. Keep OpenRouter and BYO keys in environment variables or AWS Secrets Manager only.

## Recommended simple deployment

### Backend

1. Create an RDS PostgreSQL 15 instance.
   - Database: `glassbox`
   - User: `glassbox`
   - Public access: disabled if using the same VPC as EC2
2. Create an EC2 instance with Docker.
3. Add an IAM role allowing read access to the S3 corpus bucket.
4. Copy the backend image or build on the instance:

```bash
cd backend
docker build -t glassbox-backend .
docker run -d --name glassbox-backend \
  -p 8000:8000 \
  -e DATABASE_URL='postgresql+psycopg://glassbox:REPLACE@RDS_HOST:5432/glassbox' \
  -e OPENROUTER_API_KEY='sk-or-...' \
  -e GLASSBOX_LOCAL_LLM=0 \
  -e RATE_LIMIT_PER_MIN=10 \
  -e AWS_REGION=ap-south-1 \
  -e S3_CORPUS_BUCKET=glassbox-corpus \
  glassbox-backend
```

5. Put an Application Load Balancer or API Gateway in front of the EC2 service.
6. Confirm `GET /health` returns `{"status":"ok"}`.

### Corpus and S3

The current local implementation indexes `backend/corpus` into a local file store.
For production, upload the same corpus directory to S3 and add a startup sync step:

```bash
aws s3 sync s3://glassbox-corpus/corpus ./corpus
python -m corpus.ingest
```

Keep the corpus read-only for the app runtime. Only the deployment role should update it.

### Frontend

Deploy the Next.js frontend to Vercel, Amplify, or the same EC2 host.

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=https://api.your-domain.example npm run build
npm run start
```

### Rate limit acceptance

Set `RATE_LIMIT_PER_MIN=2` temporarily and make three quick requests to a non-health
endpoint. The third response should be HTTP `429` with:

```json
{"detail":"GlassBox is busy. Please wait a minute and try again."}
```

## Later hardening

- Replace the local file vector store with managed pgvector or Chroma server if corpus size grows.
- Add Cognito or another auth layer before showing any non-synthetic data.
- Move secrets into AWS Secrets Manager.
- Add structured logs and CloudWatch dashboards.
- Run a small load test before sharing the public URL.
