#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
BACKEND_PORT="${BACKEND_PORT:-4002}"
READINESS_NAMESPACE="${READINESS_NAMESPACE:-office-manager/Application}"

cat >/usr/local/bin/publish-backend-readiness <<SCRIPT
#!/bin/bash
set -u
ready=0
if curl --fail --silent --max-time 5 "http://127.0.0.1:${BACKEND_PORT}/api/v1/readyz" >/dev/null; then
  ready=1
fi
token="\$(curl --fail --silent --max-time 2 -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' -X PUT http://169.254.169.254/latest/api/token || true)"
instance_id=""
if [ -n "\$token" ]; then
  instance_id="\$(curl --fail --silent --max-time 2 -H "X-aws-ec2-metadata-token: \$token" http://169.254.169.254/latest/meta-data/instance-id || true)"
fi
if [ -n "\$instance_id" ]; then
  aws cloudwatch put-metric-data \\
    --region "${AWS_REGION}" \\
    --namespace "${READINESS_NAMESPACE}" \\
    --metric-name Ready \\
    --dimensions "InstanceId=\$instance_id" \\
    --value "\$ready" \\
    --unit Count
fi
SCRIPT
chmod 0755 /usr/local/bin/publish-backend-readiness

cat >/etc/systemd/system/office-manager-readiness.service <<'UNIT'
[Unit]
Description=Publish Portfolio Desk backend readiness to CloudWatch
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/publish-backend-readiness
UNIT

cat >/etc/systemd/system/office-manager-readiness.timer <<'TIMER'
[Unit]
Description=Check Portfolio Desk backend readiness every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable --now office-manager-readiness.timer
