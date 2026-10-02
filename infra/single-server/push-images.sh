#!/bin/bash
# Build both images for arm64 (the server is a Graviton t4g) and push them to
# ECR. Run from the repo root with the glassbox AWS profile:
#
#   AWS_PROFILE=glassbox infra/single-server/push-images.sh <tag> https://api.<host>
set -euo pipefail

TAG="${1:?usage: push-images.sh <tag> <api-base-url>}"
API_BASE="${2:?usage: push-images.sh <tag> <api-base-url>}"
REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build --platform linux/arm64 -t "$REGISTRY/glassbox-backend:$TAG" backend
docker build --platform linux/arm64 --build-arg NEXT_PUBLIC_API_BASE="$API_BASE" \
  -t "$REGISTRY/glassbox-frontend:$TAG" frontend
docker push "$REGISTRY/glassbox-backend:$TAG"
docker push "$REGISTRY/glassbox-frontend:$TAG"
