#!/usr/bin/env bash
# Atualiza a VM com o que está no GitHub: git pull + build do front + docker compose.
#
#   ./deploy.sh           só faz algo se houver commit novo (bom para o cron)
#   ./deploy.sh --force   refaz tudo mesmo sem commit novo
#
# Deploy automático a cada minuto (bônus): crontab -e e adicione
#   * * * * * /caminho/do/repo/infra/deploy.sh >> /caminho/do/repo/infra/deploy.log 2>&1
set -euo pipefail

INFRA_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$INFRA_DIR/.." && pwd)"
cd "$ROOT_DIR"

BRANCH="${BRANCH:-main}"

if [ ! -f "$INFRA_DIR/.env" ]; then
  echo "falta $INFRA_DIR/.env (copie de infra/.env.example e preencha)" >&2
  exit 1
fi

git fetch origin "$BRANCH" -q
if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ] && [ "${1:-}" != "--force" ]; then
  exit 0
fi
git reset --hard "origin/$BRANCH"

# Compila o front dentro de um contêiner Node, assim a VM não precisa ter Node instalado.
# O compose (infra/) serve a pasta frontend/dist gerada aqui.
if [ -f "$ROOT_DIR/frontend/package.json" ]; then
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$ROOT_DIR/frontend":/app -w /app node:22-alpine \
    sh -c "npm ci || npm install; npm run build"
fi

cd "$INFRA_DIR"
docker compose up -d --build
echo "$(date '+%F %T') deploy feito: $(git rev-parse --short HEAD)"
