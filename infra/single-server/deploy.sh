#!/bin/bash
# Run on the server (as root, e.g. through SSM Run Command) from
# /opt/glassbox: render .env from SSM Parameter Store, pull the images for
# <image-tag> from ECR and (re)start the stack.
#
#   ./deploy.sh <image-tag>
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:?usage: deploy.sh <image-tag>}"
REGION=ap-south-1
PREFIX=/glassbox/prod
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

umask 077
{
  # Values are single-quoted so Compose takes them literally.
  aws ssm get-parameters-by-path --region "$REGION" --path "$PREFIX" --with-decryption \
    --query 'Parameters[].[Name,Value]' --output text |
    while IFS=$'\t' read -r name value; do
      printf "%s='%s'\n" "${name##*/}" "$value"
    done
  echo "REGISTRY=$REGISTRY"
  echo "IMAGE_TAG=$TAG"
} > .env.new
mv .env.new .env

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker compose pull --quiet
docker compose up -d --remove-orphans
docker image prune -f > /dev/null
docker compose ps
