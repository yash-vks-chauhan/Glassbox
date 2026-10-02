#!/bin/bash
# First-boot setup for the GlassBox server (Amazon Linux 2023, arm64), run as
# EC2 user data: Docker with the Compose plugin, log rotation, 2 GB of swap.
set -euo pipefail

COMPOSE_VERSION=v5.6.0

dnf install -y docker
mkdir -p /usr/local/lib/docker/cli-plugins /etc/docker /opt/glassbox
base="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64"
curl -fsSL "$base" -o /tmp/docker-compose
expected=$(curl -fsSL "$base.sha256" | awk '{print $1}')
echo "$expected  /tmp/docker-compose" | sha256sum -c -
install -m 0755 /tmp/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

cat > /etc/docker/daemon.json <<'JSON'
{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}
JSON
systemctl enable --now docker

if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap defaults 0 0' >> /etc/fstab
fi
