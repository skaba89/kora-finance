#!/usr/bin/env bash
# Restaure une sauvegarde chiffrée dans la base de production (REMPLACE les données).
# Les sauvegardes vivent dans le bucket dédié (KF-09) ; seuls les identifiants de
# sauvegarde sont utilisés, jamais ceux des pièces.
# Usage : ./restore.sh                     → liste les sauvegardes disponibles
#         ./restore.sh backups/kora-….dump.enc
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -eq 0 ]]; then
  docker compose --profile backup run --rm --no-deps backup python -m kora.scripts.backup list
  exit 0
fi
key="$1"
mkdir -p backups && chmod 700 backups
docker compose --profile backup run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backups:/backups" \
  backup python -m kora.scripts.backup download "${key}" /backups/restauration.dump

read -r -p "Remplacer TOUTES les données actuelles par cette sauvegarde ? Tapez RESTAURER : " answer
[[ "${answer}" == "RESTAURER" ]] || { echo "Abandon : rien n'a été modifié."; exit 1; }

docker compose stop web api worker
docker compose exec -T postgres pg_restore -U kora_admin -d kora --clean --if-exists \
  --single-transaction < backups/restauration.dump
docker compose up -d --wait
rm -f backups/restauration.dump
echo "Restauration terminée."
