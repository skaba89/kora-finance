#!/usr/bin/env bash
# Démarre l'API kora (:8100) et le web Next.js (:3000) en arrière-plan,
# avec attente active des ports. Nécessite recette-stack.sh puis recette-env.sh.
set -uo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
RECETTE_DIR=${RECETTE_DIR:-$(dirname "$REPO")/.recette}
LOGS=$RECETTE_DIR

# 1) API (uvicorn, factory create_app)
if ! (echo > /dev/tcp/127.0.0.1/8100) >/dev/null 2>&1; then
  if [ ! -x "$REPO/apps/api/.venv/bin/uvicorn" ]; then
    echo "ERREUR: venv API absent — exécuter 'uv sync' dans apps/api"; exit 1
  fi
  setsid sh -c "set -a; . $RECETTE_DIR/recette-api.env; set +a; \
    export PYTHONPATH=$REPO/apps/api/src; \
    cd $REPO/apps/api && nohup .venv/bin/uvicorn kora.main:create_app --factory \
    --host 127.0.0.1 --port 8100 --no-proxy-headers > $LOGS/kora-api.log 2>&1 < /dev/null &"
  for i in $(seq 1 30); do (echo > /dev/tcp/127.0.0.1/8100) >/dev/null 2>&1 && break; sleep 1; done
fi
curl -sf http://127.0.0.1:8100/health >/dev/null && echo "API OK (8100)" || {
  echo "ERREUR API"; tail -20 "$LOGS/kora-api.log"; exit 1; }

# 2) Web (Next.js dev)
if ! (echo > /dev/tcp/127.0.0.1/3000) >/dev/null 2>&1; then
  setsid sh -c "cd $REPO/apps/web && nohup npm run dev -p 3000 > $LOGS/kora-web.log 2>&1 < /dev/null &"
  for i in $(seq 1 45); do (echo > /dev/tcp/127.0.0.1/3000) >/dev/null 2>&1 && break; sleep 1; done
fi
(echo > /dev/tcp/127.0.0.1/3000) >/dev/null 2>&1 && echo "WEB OK (3000)" || {
  echo "ERREUR WEB"; tail -20 "$LOGS/kora-web.log"; exit 1; }
echo "APP RECETTE OK"
