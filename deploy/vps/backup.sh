#!/usr/bin/env bash
# Sauvegarde quotidienne : dump PostgreSQL (format personnalisé), envoi chiffré et vérifié
# dans le bucket S3 (backups/), purge des sauvegardes de plus de 30 jours (les sept plus
# récentes sont toujours gardées). Copie locale conservée 7 jours dans deploy/vps/backups.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups
chmod 700 backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="backups/kora-${stamp}.dump"

# pg_dump de la même version que le serveur, en super-utilisateur (lit toutes les lignes
# malgré la RLS), sans passer le mot de passe en argument.
docker compose exec -T postgres pg_dump -U kora_admin -d kora -Fc > "${file}"
[[ -s "${file}" ]] || { echo "Dump vide : sauvegarde annulée." >&2; exit 1; }

docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD/backups:/backups" \
  api python -m kora.scripts.backup upload "/backups/$(basename "${file}")"
docker compose run --rm --no-deps api python -m kora.scripts.backup prune --keep-days 30
find backups -name 'kora-*.dump' -mtime +7 -delete
echo "Sauvegarde terminée : ${file}"
