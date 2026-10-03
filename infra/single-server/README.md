# GlassBox on one server

The live deployment: one small EC2 instance in Mumbai runs the whole stack in
Docker. Caddy handles HTTPS, then come Postgres, the API and the web app.
It costs about $14 a month. For a larger, managed setup see
[../aws-notes.md](../aws-notes.md).

| | |
|---|---|
| Web app | <https://glassbox.15-252-203-137.sslip.io> |
| API | <https://api.glassbox.15-252-203-137.sslip.io> (`/health`) |
| Region | `ap-south-1` (Mumbai) |
| Server | `i-09c39045ae4d2e6e6`, `t4g.small` (Graviton, 2 vCPU, 2 GB) on Amazon Linux 2023, 20 GB gp3 |
| Address | Elastic IP `15.252.203.137`. [sslip.io](https://sslip.io) turns `*.15-252-203-137.sslip.io` into that IP, so no domain is needed |

## What's in the account

Everything is tagged `Project=glassbox`.

| Resource | Name | Purpose |
|---|---|---|
| EC2 instance | `glassbox` | Runs `docker-compose.yml` from `/opt/glassbox`. Termination protection is on |
| Elastic IP | `glassbox` | The fixed address the hostnames point at |
| Security group | `glassbox-web` | Inbound 80 and 443 only (plus UDP 443 for HTTP/3). There is no SSH; admin access goes through SSM |
| IAM role and instance profile | `glassbox-ec2` | SSM access, read-only ECR pulls, reading `/glassbox/prod/*` |
| ECR repositories | `glassbox-backend`, `glassbox-frontend` | The images, tagged with the git commit. The 10 most recent are kept |
| SSM parameters | `/glassbox/prod/*` | Hostnames, the app's keys, the Postgres password, SMTP settings. Secrets are SecureString |
| Lifecycle policy | DLM, volumes tagged `glassbox-backup=true` | A disk snapshot every day at 02:00 IST, kept for 7 days |
| OIDC provider and IAM role | `token.actions.githubusercontent.com`, `glassbox-github-deploy` | Lets the Deploy workflow, and only its `production` environment in this repo, push images and run the rollout command on this one server |

## Files

- `docker-compose.yml`: Caddy, Postgres 15, the API and the web app. Only Caddy publishes ports.
- `Caddyfile`: one site per hostname. Certificates come from Let's Encrypt and renew automatically.
- `bootstrap-instance.sh`: EC2 user data. It installs Docker and the Compose plugin (with its checksum verified), sets up log rotation, and adds 2 GB of swap.
- `deploy.sh`: runs on the server. It writes `.env` from the SSM parameters, pulls `<tag>` from ECR and restarts the stack.
- `push-images.sh`: runs on your machine. It builds both images for arm64 and pushes them.
- `remote-deploy.sh`: copies the three server files to `/opt/glassbox` and runs `deploy.sh <tag>` there through SSM. It prints the output and fails if the rollout fails.

## Deploy a new version

It happens by itself. When CI passes on `main`, the
[Deploy workflow](../../.github/workflows/deploy.yml) builds both images on
an arm64 runner, pushes them to ECR tagged with the commit, and rolls them
out with `remote-deploy.sh`. It then checks that the site answers. Each run
is listed under the repository's **Deployments → production**. To redeploy
by hand, run the workflow from the Actions tab.

The same steps work from your machine, with the `glassbox` AWS profile
signed in (`aws login --profile glassbox`):

```bash
TAG=$(git rev-parse --short HEAD)
AWS_PROFILE=glassbox infra/single-server/push-images.sh $TAG https://api.glassbox.15-252-203-137.sslip.io
AWS_PROFILE=glassbox infra/single-server/remote-deploy.sh i-09c39045ae4d2e6e6 $TAG
```

Migrations run when the API container starts. To roll back, deploy the
previous tag. If the newer version added a migration, also add
`GLASSBOX_SKIP_MIGRATIONS=1` to the API's environment; see
[../../docs/DEPLOYMENT-ROLLBACK-RUNBOOK.md](../../docs/DEPLOYMENT-ROLLBACK-RUNBOOK.md).

A shell on the server is
`aws ssm start-session --profile glassbox --target i-09c39045ae4d2e6e6`
(this needs the Session Manager plugin).

## Settings and secrets

`deploy.sh` reads every parameter under `/glassbox/prod/` into `.env` on each
deploy. To change one, update the parameter and redeploy:

```bash
aws ssm put-parameter --profile glassbox --region ap-south-1 --overwrite \
  --name /glassbox/prod/SMTP_FROM --type SecureString --value "GlassBox <you@example.com>"
```

`DEMO_LOGIN_ENABLED=1` puts the "Try as an advisor / compliance" buttons on
the sign-in page. Set it to `0` to make the site invite-only.

`BOOTSTRAP_SETUP_KEY` turns on `/setup` for creating a workspace's first
owner. Delete it once each workspace has its owner:
`aws ssm delete-parameter --profile glassbox --region ap-south-1 --name /glassbox/prod/BOOTSTRAP_SETUP_KEY`,
then redeploy.

## Changing the address

The web app has the API's address built into it, so a new hostname needs a
rebuild:

1. Point the new names at `15.252.203.137`. With a real domain, add an `A`
   record for the app's name and one for `api.` under it. The `sslip.io`
   names already resolve.
2. Update `/glassbox/prod/APP_HOST` and `/glassbox/prod/API_HOST`, and the
   `APP_URL` and `API_BASE_URL` variables of the repository's `production`
   environment, which the Deploy workflow builds with.
3. Run the Deploy workflow (or `push-images.sh` with the new
   `https://<API_HOST>`, then `remote-deploy.sh`). Caddy fetches
   certificates for the new names on start, and `FRONTEND_ORIGIN` (CORS and
   links in emails) follows `APP_HOST`.

The old names stop working; sessions don't carry over, so users sign in
again.

## Costs

At on-demand Mumbai prices:

| Item | Monthly cost |
|---|---|
| `t4g.small` ($0.0112/h) | about $8.20 |
| 20 GB gp3 ($0.0912/GB) | about $1.80 |
| Public IPv4 ($0.005/h) | about $3.65 |
| Snapshots and ECR | under $1 |
| **Total** | **about $14** |

The first 100 GB/month of outbound data are free. CPU credits are set to
`standard`, so a busy spell slows the server down rather than adding
charges.

## Removing it

To remove it, work in this order:

1. Turn off termination protection, then terminate the instance. This also deletes its disk.
2. Release the Elastic IP.
3. Delete the DLM policy and the snapshots it made.
4. Delete the `glassbox-backend` and `glassbox-frontend` repositories (with `--force`).
5. Delete the `/glassbox/prod/*` parameters.
6. Delete the `glassbox-web` security group.
7. Delete the `glassbox-ec2` instance profile and role, the `glassbox-github-deploy` role and the GitHub OIDC provider.
8. Delete the repository's `production` environment and the Deploy workflow.
