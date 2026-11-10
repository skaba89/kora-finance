#!/usr/bin/env bash
# Alerte d'exploitation (KF-12) : instanciée par OnFailure= (nom de l'unité en
# argument, %i). Trace locale horodatée, puis email d'exploitation via le conteneur
# backup (`kora.scripts.notify`, destinataire KORA_ALERT_EMAIL). Anti-tempête : au
# plus un email par unité défaillante et par tranche de 4 h ; la trace, elle, est
# toujours écrite.
set -euo pipefail
cd "$(dirname "$0")"
# Image épinglée à la release en cours (KF-11), comme backup.sh.
export KORA_IMAGE_TAG="${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}"
unit="${1:-unité-inconnue}"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p backups/alertes
chmod 700 backups
echo "${now} ÉCHEC ${unit}" >> backups/alertes/journal.log

stamp=$(date -u +%s)
state="backups/alertes/${unit}.dernier"
if [[ -f "${state}" ]]; then
  last=$(cat "${state}" 2>/dev/null || echo 0)
  if (( stamp - last < 4 * 3600 )); then
    echo "Alerte ${unit} déjà envoyée il y a moins de 4 h : pas de nouvel email."
    exit 0
  fi
fi
printf '%s' "${stamp}" > "${state}"

docker compose --profile backup run --rm --no-deps backup \
  python -m kora.scripts.notify \
  "Kora Finance : échec de ${unit}" \
  "L'unité systemd ${unit} a échoué le ${now} UTC sur $(hostname).
Journal : journalctl -u ${unit} -n 50 --no-pager
Traces locales : deploy/vps/backups/alertes/journal.log"
echo "Alerte ${unit} envoyée à KORA_ALERT_EMAIL."
