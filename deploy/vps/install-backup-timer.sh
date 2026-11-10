#!/usr/bin/env bash
# Installe la supervision d'exploitation (systemd, KF-12) : sauvegarde quotidienne,
# contrôle de fraîcheur, sonde externe, unité d'alerte. À lancer une fois, avec sudo
# disponible. Les alertes exigent KORA_ALERT_EMAIL dans deploy/vps/.env.
set -euo pipefail
cd "$(dirname "$0")"
dir="$PWD"
units=(
  kora-backup.service kora-backup.timer
  kora-freshness.service kora-freshness.timer
  kora-probe.service kora-probe.timer
  kora-alert@.service
)
for unit in "${units[@]}"; do
  sed -e "s|__USER__|$(id -un)|" -e "s|__DIR__|${dir}|g" "${unit}" \
    | sudo tee "/etc/systemd/system/${unit}" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now kora-backup.timer kora-freshness.timer kora-probe.timer
systemctl list-timers kora-backup.timer kora-freshness.timer kora-probe.timer --no-pager
echo "Supervision installée. Journaux : journalctl -u kora-backup -u kora-freshness -u kora-probe -u kora-alert"
