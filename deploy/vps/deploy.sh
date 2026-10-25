#!/usr/bin/env bash
# Déploie (ou met à jour) Kora : récupère main, reconstruit les images, applique les
# migrations (service migrate) et redémarre la pile. À lancer sur le serveur, depuis
# n'importe quel répertoire. Les données (volumes) ne sont jamais supprimées.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]] || grep -qE '=__A_REMPLIR__$' .env; then
  echo "deploy/vps/.env absent ou incomplet : lancer ./init-env.sh et le compléter." >&2
  exit 1
fi

branch=$(git -C ../.. rev-parse --abbrev-ref HEAD)
if [[ "${branch}" != "main" ]]; then
  echo "Copie sur la branche « ${branch} » : la production se déploie uniquement depuis main." >&2
  exit 1
fi

if [[ "${1:-}" != "--sans-git" ]]; then
  git -C ../.. fetch --quiet origin main
  git -C ../.. merge --ff-only --quiet origin/main
fi
echo "Version : $(git -C ../.. log -1 --format='%h %s')"

# Mode proxy existant : réseau partagé avec le proxy du serveur.
if grep -qE '^COMPOSE_FILE=.*proxy-externe' .env && ! docker network inspect kora-edge > /dev/null 2>&1; then
  docker network create kora-edge > /dev/null
  echo "Réseau kora-edge créé : y raccorder le proxy du serveur (docs/DEPLOIEMENT.md)."
fi

docker compose build --pull
# Vérifie le stockage S3 avant de remplacer quoi que ce soit (clé, bucket, https).
docker compose run --rm --no-deps api python -m kora.scripts.check_storage
docker compose up -d --wait --remove-orphans
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
echo "Kora est en ligne : https://$(grep -E '^KORA_DOMAIN=' .env | cut -d= -f2)"
