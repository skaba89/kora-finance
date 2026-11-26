#!/usr/bin/env bash
# Génère les fichiers d'environnement de recette locale (API + web).
# Secrets générés à la première exécution puis conservés (idempotent).
# Aucune valeur spécifique à un hébergement : KORA_PUBLIC_URL est un paramètre.
#
# Usage :
#   ./recette-env.sh                              # URL publique par défaut (http://localhost:3000)
#   KORA_PUBLIC_URL=https://apercu.exemple ./recette-env.sh
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
RECETTE_DIR=${RECETTE_DIR:-$(dirname "$REPO")/.recette}
mkdir -p "$RECETTE_DIR"
ENVFILE=$RECETTE_DIR/recette-api.env

if [ ! -f "$ENVFILE" ]; then
  JWT=$(openssl rand -hex 32)
  FERNET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
  cat > "$ENVFILE" <<EOF
KORA_ENV=local
KORA_LOG_LEVEL=INFO
KORA_DATABASE_URL=postgresql+psycopg://kora_app:kora_app_local@127.0.0.1:54330/kora_test
KORA_DATABASE_MIGRATION_URL=postgresql+psycopg://kora_owner:kora_owner_local@127.0.0.1:54330/kora_test
KORA_REDIS_URL=redis://127.0.0.1:63790/0
KORA_JWT_SECRET=$JWT
KORA_ENCRYPTION_KEYS=$FERNET
KORA_EMAIL_BACKEND=disabled
KORA_EMAIL_FROM="Kora Finance <no-reply@kora.local>"
KORA_PUBLIC_URL=${KORA_PUBLIC_URL:-http://localhost:3000}
KORA_S3_ENDPOINT_URL=http://127.0.0.1:9000
KORA_S3_REGION=garage
KORA_S3_BUCKET=kora
KORA_S3_ACCESS_KEY_ID=kora-local
KORA_S3_SECRET_ACCESS_KEY=kora-local-secret
EOF
  chmod 600 "$ENVFILE"
  echo "   $ENVFILE écrit (secrets générés)"
else
  echo "   $ENVFILE déjà présent (conservé)"
fi

# Environnement du web (BFF) : l'app web appelle l'API en interne.
cat > "$REPO/apps/web/.env.local" <<EOF
KORA_API_INTERNAL_URL=http://127.0.0.1:8100
KORA_PUBLIC_URL=${KORA_PUBLIC_URL:-http://localhost:3000}
EOF
echo "   apps/web/.env.local écrit"
echo "ENV RECETTE OK"
