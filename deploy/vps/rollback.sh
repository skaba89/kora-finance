#!/usr/bin/env bash
# Retour arrière (KF-11) : redémarre la pile sur la release précédente connue — les
# images immuables kora-api:<sha> / kora-web:<sha> construites par deploy.sh (consignées
# dans releases.log avec leurs IDs). Les volumes de données ne sont jamais touchés.
#
# Convention expand/contract (docs/DEPLOIEMENT.md §4) : le schéma PostgreSQL n'est pas
# migré en arrière — ne revenir qu'à une version compatible (en règle générale, la
# version immédiatement précédente). Si la migration de la version défaillante a
# introduit des colonnes, elles restent présentes et sans effet sur l'ancien code.
#
# Usage : ./rollback.sh
set -euo pipefail
cd "$(dirname "$0")"

current=$(cat .release 2>/dev/null || true)
previous=$(cat .previous-release 2>/dev/null || true)
if [[ -z "${previous}" || "${previous}" == "${current}" ]]; then
  echo "Aucune version précédente connue (deploy/vps/.previous-release) : rien à restaurer." >&2
  echo "Les versions déployées sont consignées dans deploy/vps/releases.log ; pour revenir" >&2
  echo "à une version plus ancienne : KORA_IMAGE_TAG=<sha> docker compose up -d --wait." >&2
  exit 1
fi
if ! docker image inspect "kora-api:${previous}" > /dev/null 2>&1 \
  || ! docker image inspect "kora-web:${previous}" > /dev/null 2>&1; then
  echo "Les images de la release « ${previous} » ne sont plus présentes localement." >&2
  echo "Versions disponibles : cut -f2 releases.log ; docker images 'kora-*'." >&2
  exit 1
fi

echo "Retour de ${current:-?} vers ${previous}…"
KORA_IMAGE_TAG="${previous}" docker compose up -d --wait --remove-orphans
echo "${previous}" > .release
echo "${current}" > .previous-release
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
echo "Retour à ${previous} terminé. Vérifier : docker compose logs --tail=50 api."
echo "Pour rejouer la version écartée : ./deploy.sh --sans-git (elle est toujours sur main)."
