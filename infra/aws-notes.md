# Deploying GlassBox on AWS

A runbook for putting GlassBox on AWS: the API and the web app as two
containers, the audit store on RDS PostgreSQL, HTTPS through an Application
Load Balancer. Everything here uses the images and settings already in the
repo; nothing needs a paid model provider.

It is written for the AWS console plus a few CLI commands. There is no
Terraform or CDK template yet, so resource names below are suggestions.

## What you end up with

```
            https://app.example.com            https://api.example.com
                       │                                  │
                ┌──────▼──────────────── ALB (ACM certificate) ────────▼──────┐
                │  host app.*  → frontend target group (port 3000, path /)    │
                │  host api.*  → backend target group  (port 8000, /health)   │
                └──────┬───────────────────────────────────────┬──────────────┘
          ECS Fargate  │ glassbox-frontend                      │ glassbox-backend
                       │ (Next.js standalone)                   │ (FastAPI, migrates on start)
                       │                                        │
                       │              RDS PostgreSQL 15 ◄───────┘ private subnets
                       │              Secrets Manager (keys, DB URL, SMTP)
                       │              SES SMTP (invites, password resets)
```

Use **one registrable domain** for both hostnames (for example
`app.example.com` and `api.example.com`). The refresh cookie is
`SameSite=Lax` and HttpOnly; if the web app and the API sit on unrelated
domains (say `*.vercel.app` and `*.amazonaws.com`), the browser won't send
it and users get signed out every 15 minutes.

## Billing guardrails (do these first)

1. Create AWS Budgets alerts at $20, $50 and $100.
2. No GPU instances: the default answer path is the local evidence engine,
   which runs on CPU in milliseconds.
3. Use the smallest sizes to start: Fargate 0.5 vCPU / 1 GB for the API,
   0.25 vCPU / 0.5 GB for the web app, `db.t4g.micro` for RDS.
4. Delete the stack (or scale services to 0 and stop RDS) after demos.

## 1. Build and push the images

```bash
AWS_REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

aws ecr create-repository --repository-name glassbox-backend
aws ecr create-repository --repository-name glassbox-frontend
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $REGISTRY

# The API image builds its retrieval index from backend/corpus at build time.
docker build --platform linux/amd64 -t $REGISTRY/glassbox-backend:v1 backend
# The browser calls the API at this URL; it is compiled into the bundle.
docker build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_API_BASE=https://api.example.com \
  -t $REGISTRY/glassbox-frontend:v1 frontend

docker push $REGISTRY/glassbox-backend:v1
docker push $REGISTRY/glassbox-frontend:v1
```

Tag images with a version (or the git SHA) rather than `latest`, so a task
definition always names exactly what runs.

## 2. Database

Create an RDS PostgreSQL 15 instance (the test suite runs on 15):

- database `glassbox`, user `glassbox`, a generated password;
- private subnets only, no public access;
- a security group that accepts 5432 only from the backend service's
  security group;
- automated backups on (7 days or more) and deletion protection on.

The connection string the app expects:

```
postgresql+psycopg://glassbox:<password>@<rds-endpoint>:5432/glassbox
```

The schema comes from Alembic. The backend image runs `alembic upgrade head`
every time a task starts; migrations hold a Postgres advisory lock, so tasks
starting together migrate one at a time. To migrate as a separate step
instead, run a one-off task with the command `alembic upgrade head` and set
`GLASSBOX_SKIP_MIGRATIONS=1` on the service.

## 3. Secrets

Generate the application keys once per environment, from the repo root:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/init_secrets.py
```

Store each value in Secrets Manager and reference them from the backend task
definition's `secrets` section (so they arrive as environment variables):

| Variable | Notes |
|---|---|
| `JWT_SIGNING_KEY`, `JWT_ACTIVE_KID` | Signs access tokens. Rotating it only forces new 15-minute access tokens; sessions continue through refresh. |
| `APP_ENCRYPTION_KEY`, `APP_ENCRYPTION_KID` | AES-GCM key for MFA secrets and BYO model keys. To rotate, set the new key and list the old one in `APP_ENCRYPTION_PREVIOUS_KEYS` as `kid:key`. |
| `COOKIE_SECRET` | Reserved; set it anyway. |
| `DATABASE_URL` | Contains the RDS password. |
| `SMTP_PASSWORD` | SES SMTP credentials (step 5). |
| `BOOTSTRAP_SETUP_KEY` | Only while creating the first owner (step 7). |

With `GLASSBOX_PRODUCTION_MODE=1` the API refuses to start if any of the
first three still has its development default.

## 4. Backend service

Task definition `glassbox-backend`: the backend image, port 8000, 0.5 vCPU /
1 GB, logs to CloudWatch with the `awslogs` driver (logs are JSON, with
secrets redacted). Environment:

```bash
GLASSBOX_PRODUCTION_MODE=1
GLASSBOX_LOCAL_EVIDENCE_MODE=1      # the free, private answer engine
GLASSBOX_LOCAL_LLM=1
APPROVED_MODELS=                    # no hosted model route
FRONTEND_ORIGIN=https://app.example.com   # CORS allowlist and links in emails
REFRESH_COOKIE_SECURE=1
FORWARDED_ALLOW_IPS=10.0.0.0/16     # the VPC CIDR: trust the ALB's X-Forwarded-For
SMTP_HOST=email-smtp.ap-south-1.amazonaws.com
SMTP_PORT=587
SMTP_USE_TLS=1
SMTP_USERNAME=<SES SMTP user>
SMTP_FROM=no-reply@example.com
ACCESS_REQUEST_NOTIFY_EMAIL=ops@example.com   # optional: where /contact requests go
```

`FORWARDED_ALLOW_IPS` matters: rate limits and the security log key on the
client IP, and without it every request appears to come from the load
balancer, so one busy minute locks everyone out of sign-in. Only set it when
the tasks accept traffic from the ALB alone (security group rule).

Service: Fargate, private subnets, desired count 1 (2 for availability; the
nightly determinism run is claimed once per tenant per day, so replicas don't
repeat it). Target group: HTTP 8000, health check path `/health`.

Hosted models are optional and gated; see
[docs/PRODUCTION-LLM.md](../docs/PRODUCTION-LLM.md) before setting
`GLASSBOX_LOCAL_EVIDENCE_MODE=0`.

## 5. Email (SES)

Verify the sending domain (or address) in SES, create SMTP credentials, and
request production access if you need to email addresses outside your
verified identities. Invitations and password resets go out through it;
without `SMTP_HOST` they are written to files inside the container instead.

## 6. Frontend service and the load balancer

Task definition `glassbox-frontend`: the frontend image, port 3000, 0.25 vCPU /
0.5 GB. Environment:

```bash
BACKEND_API_BASE=https://api.example.com   # server-side requests (optional)
```

Target group: HTTP 3000, health check path `/`.

Load balancer: an internet-facing ALB in public subnets with an ACM
certificate for both hostnames, HTTP→HTTPS redirect on port 80, and two
HTTPS listener rules by host header (`app.example.com` → frontend,
`api.example.com` → backend). Point both DNS names at the ALB (Route 53
alias records).

## 7. First owner

1. Add `BOOTSTRAP_SETUP_KEY` (a long random string) to the backend's secrets
   and redeploy.
2. Open `https://app.example.com/setup`, enter the key, a workspace name and
   ID, your email and password, then scan the QR code with an authenticator
   app and save the recovery codes.
3. Remove `BOOTSTRAP_SETUP_KEY` and redeploy. Invite everyone else from
   **Admin → Users**.

Workspace ID `demo` holds the four sample clients and their documents; use
it to try the product, and a new ID for real work (a new workspace starts
with no clients or documents).

## 8. Check the deployment

- `curl https://api.example.com/health` returns `{"status":"ok"}`.
- **Admin → System** shows environment `production`, database `postgresql`
  and inference `local:glassbox-evidence-engine`.
- In the `demo` workspace, ask "Can client C001 put 40% into fund F100?": the
  answer is flagged with four cited sources, and **Open replay** shows the
  stored decision.
- **Admin → Audit verify** reports the hash chain intact.
- Rate limiting: the eleventh sign-in request within a minute from one
  address gets HTTP 429 with a `Retry-After` header (and an account locks
  for 15 minutes after five wrong passwords).

## Operating it

- **Upgrades:** build and push a new image tag, update the task definition,
  redeploy. Migrations run as the new tasks start.
- **Rollbacks:** redeploy the previous image tag with
  `GLASSBOX_SKIP_MIGRATIONS=1` (an older image can't migrate a newer schema);
  see [docs/DEPLOYMENT-ROLLBACK-RUNBOOK.md](../docs/DEPLOYMENT-ROLLBACK-RUNBOOK.md).
- **Corpus changes:** the retrieval index is built into the backend image,
  so edit `backend/corpus/` and rebuild.
- **Backups and audit data:** rely on RDS backups and point-in-time restore.
  The database itself refuses `DELETE` and `TRUNCATE` on the audit tables;
  corrections are appended to `decision_corrections`, never edited in place.
- **Logs:** CloudWatch Logs, one JSON line per event, with request, tenant
  and user IDs.
- **Rotating the encryption key:** set the new `APP_ENCRYPTION_KEY` and
  `APP_ENCRYPTION_KID`, keep the old pair in `APP_ENCRYPTION_PREVIOUS_KEYS`,
  redeploy. Existing secrets keep decrypting and are re-encrypted with the
  new key on their next write.

## Single EC2 instance (demo only)

For a short-lived demo, one `t3.small` with Docker can run the same two
images with `docker run`, using the environment above, plus RDS or a
Postgres container with a volume. Put it behind HTTPS (an ALB, or Caddy on
the instance); without HTTPS, `REFRESH_COOKIE_SECURE=1` stops sign-in
from persisting. The repo's `docker-compose.yml` is a development stack
(dev secrets, production mode off) and should not be exposed to the
internet as-is.
