#!/usr/bin/env bash
# Sauvegarde quotidienne : dump PostgreSQL (format personnalisé), envoi chiffré et vérifié
# dans le bucket S3 DÉDIÉ aux sauvegardes (KF-09 : bucket et clé distincts du stockage des
# pièces ; la clé de sauvegarde ne porte aucun droit de suppression — la rétention est
# administrée côté fournisseur, la purge manuelle `prune` exige la clé d'administration
# hors VPS). Copie locale conservée 7 jours dans deploy/vps/backups.
set -euo pipefail
cd "$(dirname "$0")"
# Image épinglée à la release en cours (KF-11) : .release est écrit par deploy.sh ;
# fallback : l'alias :prod (pile construite par make/compose hors deploy.sh).
export KORA_IMAGE_TAG="${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}"
mkdir -p backups
chmod 700 backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="backups/kora-${stamp}.dump"

# pg_dump de la même version que le serveur, en super-utilisateur (lit toutes les lignes
# malgré la RLS), sans passer le mot de passe en argument.
docker compose exec -T postgres pg_dump -U kora_admin -d kora -Fc > "${file}"
[[ -s "${file}" ]] || { echo "Dump vide : sauvegarde annulée." >&2; exit 1; }

docker compose --profile backup run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backups:/backups" \
  backup python -m kora.scripts.backup upload "/backups/$(basename "${file}")"
find backups -name 'kora-*.dump' -mtime +7 -delete
echo "Sauvegarde terminée : ${file}"
