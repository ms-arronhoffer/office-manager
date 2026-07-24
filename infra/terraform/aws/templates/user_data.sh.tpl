#!/bin/bash
# Bootstrap script for the Phase 1 application EC2 instance:
#   1. Ensures the SSM Agent is installed and running (Session Manager access).
#   2. Installs Docker + the Docker Compose CLI plugin (system-wide).
#   3. Clones the application repo so the SSM-driven deploy can run
#      `docker compose -f docker-compose.prod.yml` from a working tree.
# The box no longer registers a self-hosted GitHub Actions runner: the `prod`
# deploy workflow drives the container pull/restart remotely via SSM
# `send-command` from the on-prem `docker-build` runner, so nothing here is
# lost/needs re-registration when the instance is replaced.
# Idempotent: safe to re-run (e.g. on instance replacement).
set -euxo pipefail

# ── SSM Agent ─────────────────────────────────────────────────────────────────
# Session Manager (SSM) is how we shell into this box without opening port 22
# AND how the deploy workflow runs commands on it. The IAM role attached in
# ec2.tf grants AmazonSSMManagedInstanceCore for exactly this. On AL2023 the
# agent ships pre-installed, but we install + enable it explicitly here (and do
# it FIRST, before the slower/flakier steps below) so a failure later in this
# script under `set -e` can never leave the instance unreachable via SSM.
# `dnf install` is a no-op when the agent is already present.
dnf install -y amazon-ssm-agent || true
systemctl enable --now amazon-ssm-agent || true

dnf update -y
dnf install -y docker git jq acl python3
systemctl enable --now docker
usermod -aG docker ec2-user

# ── Docker Compose CLI plugin ─────────────────────────────────────────────────
# Amazon Linux 2023's `docker` package does NOT bundle the Compose v2 CLI
# plugin, so `docker compose ...` is unavailable out of the box. Install it
# system-wide (into Docker's global cli-plugins dir) so it is on PATH for every
# user — importantly for `root`, which is the identity the SSM-driven deploy
# command runs as. This replaces the per-deploy "Ensure Docker Compose is
# available" self-heal that used to run on the old aws-prod runner.
COMPOSE_VERSION="v2.29.7"
case "$(uname -m)" in
  x86_64 | amd64) COMPOSE_ARCH="x86_64" ;;
  aarch64 | arm64) COMPOSE_ARCH="aarch64" ;;
  *)
    echo "Unsupported architecture for Docker Compose plugin: $(uname -m)" >&2
    COMPOSE_ARCH=""
    ;;
esac
if [ -n "$COMPOSE_ARCH" ] && ! docker compose version >/dev/null 2>&1; then
  install -d /usr/local/lib/docker/cli-plugins
  curl -fsSL \
    "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-$COMPOSE_ARCH" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# ── Application working tree ──────────────────────────────────────────────────
# Clone the repository so `docker compose -f docker-compose.prod.yml` can run
# from a real working tree. The deploy workflow checks out the exact commit
# being shipped before running compose, so a stale clone here is fine — this is
# just a warm cache. Public repo, so no credentials are needed.
sudo -u ec2-user git clone "https://github.com/${github_repo}.git" "/home/ec2-user/office-manager" || true
