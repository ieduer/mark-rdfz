#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_HOST="hostdzire"
REMOTE_DIR="/opt/mark-rdfz"

echo "=== [1/5] Syncing project files from ${SCRIPT_DIR} to ${REMOTE_HOST}:${REMOTE_DIR} ==="
ssh "${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR}"
rsync -avz --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='.scratch' \
    "${SCRIPT_DIR}/" "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "=== [2/5] Setting up SSL Certificate for mark.rdfz.net on VPS ==="
ssh "${REMOTE_HOST}" 'bash -s' <<'EOF'
if [ ! -f /etc/ssl/certs/mark.rdfz.net.crt ]; then
    mkdir -p /etc/ssl/certs /etc/ssl/private
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/private/mark.rdfz.net.key \
        -out /etc/ssl/certs/mark.rdfz.net.crt \
        -subj "/CN=mark.rdfz.net"
    chmod 600 /etc/ssl/private/mark.rdfz.net.key
    echo "Self-signed certificate generated."
else
    echo "Certificate already exists."
fi
EOF

echo "=== [3/5] Configuring Nginx ==="
ssh "${REMOTE_HOST}" 'bash -s' <<'EOF'
cp -f /opt/mark-rdfz/nginx/mark.rdfz.net.conf /etc/nginx/sites-available/mark.rdfz.net
ln -sf /etc/nginx/sites-available/mark.rdfz.net /etc/nginx/sites-enabled/mark.rdfz.net
nginx -t
systemctl reload nginx
EOF

echo "=== [4/5] Building & Launching Docker Container ==="
ssh "${REMOTE_HOST}" 'bash -s' <<'EOF'
cd /opt/mark-rdfz
docker compose down || true
docker compose up -d --build
EOF

echo "=== [5/5] Health Check ==="
sleep 3
ssh "${REMOTE_HOST}" "curl -sI http://127.0.0.1:8880/ | head -n 5"
echo "Deploy completed successfully!"
