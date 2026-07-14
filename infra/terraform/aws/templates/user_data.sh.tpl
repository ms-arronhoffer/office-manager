#!/bin/bash
# Bootstrap script for the Phase 1 application EC2 instance:
#   1. Installs Docker + the Docker Compose plugin.
#   2. Registers this instance as a GitHub Actions self-hosted runner labeled
#      "aws-prod" so the `prod` branch deploy workflow can target it.
# Idempotent: safe to re-run (e.g. on instance replacement).
set -euxo pipefail

dnf update -y
dnf install -y docker git jq
systemctl enable --now docker
usermod -aG docker ec2-user

# ── GitHub Actions self-hosted runner ─────────────────────────────────────────
GITHUB_REPO="${github_repo}"
RUNNER_LABELS="${github_runner_labels}"
RUNNER_PAT="${github_runner_pat}"
RUNNER_USER="ec2-user"
RUNNER_HOME="/home/$RUNNER_USER/actions-runner"

if [ -n "$RUNNER_PAT" ]; then
  mkdir -p "$RUNNER_HOME"
  cd "$RUNNER_HOME"

  RUNNER_VERSION=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r '.tag_name' | sed 's/^v//')
  ARCH="arm64" # matches the al2023-arm64 AMI selected in network.tf
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-$ARCH-$RUNNER_VERSION.tar.gz"
  tar xzf runner.tar.gz
  rm runner.tar.gz
  chown -R "$RUNNER_USER":"$RUNNER_USER" "$RUNNER_HOME"

  # Mint a short-lived (1 hour) registration token from the long-lived PAT.
  # The PAT itself is never written to disk beyond this boot script's log.
  REG_TOKEN=$(curl -fsSL -X POST \
    -H "Authorization: token $RUNNER_PAT" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GITHUB_REPO/actions/runners/registration-token" \
    | jq -r '.token')

  sudo -u "$RUNNER_USER" bash -c "
    cd '$RUNNER_HOME' && \
    ./config.sh --unattended \
      --url 'https://github.com/$GITHUB_REPO' \
      --token '$REG_TOKEN' \
      --name 'aws-prod-$(hostname)' \
      --labels '$RUNNER_LABELS' \
      --work '_work'
  "

  ./svc.sh install "$RUNNER_USER"
  ./svc.sh start
else
  echo "github_runner_pat not provided; skipping self-hosted runner registration." \
    "Register manually later or re-run this bootstrap with the PAT set."
fi

# Clone the repository so `docker compose -f docker-compose.prod.yml` can be
# run by the deploy workflow without a fresh checkout step needing extra setup.
sudo -u ec2-user git clone "https://github.com/${github_repo}.git" "/home/ec2-user/office-manager" || true
