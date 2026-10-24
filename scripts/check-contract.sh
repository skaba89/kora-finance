#!/usr/bin/env bash
# Régénère le contrat OpenAPI et les types TypeScript, puis échoue s'ils diffèrent
# de la version committée : un changement d'API doit toujours être accompagné de
# la mise à jour du frontend.
#   ./scripts/check-contract.sh          → vérification (CI)
#   ./scripts/check-contract.sh --write  → mise à jour des fichiers
set -euo pipefail
cd "$(dirname "$0")/.."
export KORA_UID="${KORA_UID:-$(id -u)}" KORA_GID="${KORA_GID:-$(id -g)}"

# Image construite d'abord, sorties sur stderr : sur une machine vierge (CI), le journal
# du build ne doit pas se mêler au contrat exporté sur stdout.
docker compose build api-tools >&2
exported="$(mktemp)"
trap 'rm -f "$exported"' EXIT
docker compose run --rm --no-deps -T api-tools \
  python -m kora.scripts.export_openapi > "$exported"
# Export invalide (sortie parasite…) : échec explicite plutôt qu'un contrat corrompu.
docker compose run --rm --no-deps -T api-tools \
  python -c 'import json, sys; json.load(sys.stdin)' < "$exported"
cp "$exported" apps/api/openapi.json
docker compose run --rm --no-deps -T web-tools npm run --silent gen:api

if [[ "${1:-}" == "--write" ]]; then
  echo "Contrat régénéré."
  exit 0
fi
if ! git diff --exit-code -- apps/api/openapi.json apps/web/src/lib/api/schema.ts; then
  echo "ERREUR : le contrat d'API a changé. Lancer ./scripts/check-contract.sh --write et committer." >&2
  exit 1
fi
echo "Contrat d'API à jour."
