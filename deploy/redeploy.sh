#!/bin/bash

set -euo pipefail

cd /opt/gohorses

echo "== codigo =="
git fetch origin main
git checkout -B main origin/main
git reset --hard origin/main
git log --oneline -1

echo "== backend =="
cd backend
.venv/bin/pip install -r requirements.txt
PATH="$PWD/.venv/bin:$PATH" .venv/bin/prisma generate
PATH="$PWD/.venv/bin:$PATH" .venv/bin/prisma db push

sudo cp /opt/gohorses/deploy/gohorses-api.service /etc/systemd/system/gohorses-api.service
sudo systemctl daemon-reload
sudo systemctl restart gohorses-api

echo "== frontend =="
cd ../frontend
npm ci
NODE_OPTIONS=--max-old-space-size=384 npm run build

sudo rm -rf /var/www/gohorses/frontend/dist
sudo cp -r dist /var/www/gohorses/frontend/
sudo chmod -R a+rX /var/www/gohorses/frontend

echo "== caddy =="
sudo cp /opt/gohorses/deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "== health =="
sleep 1
curl -fsS http://127.0.0.1:8088/api/health
curl -fsS -o /dev/null http://127.0.0.1:8080/
echo
echo "deploy OK: $(git -C /opt/gohorses log --oneline -1)"
