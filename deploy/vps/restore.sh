#!/usr/bin/env bash
# Restaure une sauvegarde chiffrée dans la base de production (REMPLACE les données).
# Les sauvegardes vivent dans le bucket dédié (KF-09) ; seuls les identifiants de
# sauvegarde sont utilisés, jamais ceux des pièces.
# Usage : ./restore.sh                     → liste les sauvegardes disponibles
#         ./restore.sh backups/kora-….dump.enc
set -euo pipefail
cd "$(dirname "$0")"
# Image épinglée à la release en cours (KF-11) : .release est écrit par deploy.sh ;
# fallback : l'alias :prod (pile construite par make/compose hors deploy.sh).
export KORA_IMAGE_TAG="${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}"
if [[ $# -eq 0 ]]; then
  docker compose --profile backup run --rm --no-deps backup python -m kora.scripts.backup list
  exit 0
fi
key="$1"
# KF-23 : la clé est imposée au format des sauvegardes du bucket dédié — ni
# traversée de préfixe, ni clé hors sauvegardes.
if [[ ! "$key" =~ ^backups/[A-Za-z0-9][A-Za-z0-9._-]*\.enc$ ]]; then
  echo "Clé de sauvegarde invalide : $key (format attendu : backups/kora-….dump.enc)"
  exit 1
fi
mkdir -p backups && chmod 700 backups
# KF-23 : le dump déchiffré est effacé quoi qu'il arrive (échec, abandon, succès) —
# jamais de copie en clair qui traîne sur le serveur.
trap 'rm -f backups/restauration.dump' EXIT
docker compose --profile backup run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/backups:/backups" \
  backup python -m kora.scripts.backup download "${key}" /backups/restauration.dump

# KF-23 : le fichier déchiffré doit être un dump PostgreSQL au format custom — vérifié
# AVANT la confirmation destructrice (un fichier corrompu ou vide ne remplace rien).
if [[ "$(head -c 5 backups/restauration.dump 2>/dev/null)" != "PGDMP" ]]; then
  echo "Fichier restauré invalide (signature PGDMP absente) : rien n'a été modifié."
  exit 1
fi

read -r -p "Remplacer TOUTES les données actuelles par cette sauvegarde ? Tapez RESTAURER : " answer
[[ "${answer}" == "RESTAURER" ]] || { echo "Abandon : rien n'a été modifié."; exit 1; }

docker compose stop web api worker
docker compose exec -T postgres pg_restore -U kora_admin -d kora --clean --if-exists \
  --single-transaction < backups/restauration.dump
docker compose up -d --wait
rm -f backups/restauration.dump
echo "Restauration terminée."
