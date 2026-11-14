#!/usr/bin/env bash
# Atualiza a VM com o que está no GitHub: git pull + build do front + docker compose.
#
#   ./deploy.sh           só faz algo se houver commit novo (bom para o cron)
#   ./deploy.sh --force   refaz tudo mesmo sem commit novo
#
# Deploy automático a cada minuto (bônus): crontab -e e adicione
#   * * * * * /caminho/do/repo/deploy.sh >> /caminho/do/repo/deploy.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="${BRANCH:-main}"

git fetch origin "$BRANCH" -q
if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ] && [ "${1:-}" != "--force" ]; then
  exit 0
fi
git reset --hard "origin/$BRANCH"

# Compila o front dentro de um contêiner Node, assim a VM não precisa ter Node instalado.
if [ -f frontend/package.json ]; then
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/frontend":/app -w /app node:22-alpine \
    sh -c "npm ci || npm install; npm run build"
fi

docker compose up -d --build
echo "$(date '+%F %T') deploy feito: $(git rev-parse --short HEAD)"
