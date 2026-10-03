#!/bin/bash
# Copy the server files (docker-compose.yml, Caddyfile, deploy.sh) to
# /opt/glassbox on the server and run `deploy.sh <tag>` there, through SSM
# Run Command. Prints the server's output and fails if the deploy fails.
# Needs AWS credentials: the glassbox profile locally, OIDC in the Deploy
# workflow.
#
#   infra/single-server/remote-deploy.sh <instance-id> <tag>
set -euo pipefail
cd "$(dirname "$0")"

INSTANCE="${1:?usage: remote-deploy.sh <instance-id> <tag>}"
TAG="${2:?usage: remote-deploy.sh <instance-id> <tag>}"
REGION="${AWS_REGION:-ap-south-1}"

parameters=$(python3 - "$TAG" <<'PY'
import base64, json, sys

lines = ["set -euo pipefail", "mkdir -p /opt/glassbox", "cd /opt/glassbox"]
for name in ("docker-compose.yml", "Caddyfile", "deploy.sh"):
    with open(name, "rb") as handle:
        lines.append(f"echo {base64.b64encode(handle.read()).decode()} | base64 -d > {name}")
lines += ["chmod 0755 deploy.sh", f"./deploy.sh {sys.argv[1]}"]
print(json.dumps({"commands": lines}))
PY
)

invocation() {
  aws ssm get-command-invocation --region "$REGION" --command-id "$CID" \
    --instance-id "$INSTANCE" --query "$1" --output text
}

CID=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript --timeout-seconds 900 --comment "Deploy $TAG" \
  --parameters "$parameters" --query Command.CommandId --output text)
echo "SSM command $CID: deploying $TAG"
while true; do
  STATUS=$(invocation Status 2>/dev/null || echo Pending)
  case "$STATUS" in
    Pending | InProgress | Delayed) sleep 5 ;;
    *) break ;;
  esac
done
invocation StandardOutputContent
if [ "$STATUS" != Success ]; then
  invocation StandardErrorContent >&2
  echo "Deploy $TAG failed: $STATUS" >&2
  exit 1
fi
