#!/usr/bin/env bash
# Crée deploy/vps/.env (secrets aléatoires) puis liste les valeurs encore à renseigner.
set -euo pipefail
cd "$(dirname "$0")"
../../scripts/init-env.sh deploy/vps/env.example deploy/vps/.env
missing=$(grep -E '=__A_REMPLIR__$' .env | cut -d= -f1 || true)
if [[ -n "$missing" ]]; then
  echo "À renseigner dans deploy/vps/.env (nano deploy/vps/.env) :" >&2
  echo "$missing" | sed 's/^/  - /' >&2
  exit 1
fi
echo "deploy/vps/.env est complet."
