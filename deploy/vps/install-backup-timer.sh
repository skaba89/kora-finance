#!/usr/bin/env bash
# Installe la sauvegarde quotidienne (systemd). À lancer une fois, avec sudo disponible.
set -euo pipefail
cd "$(dirname "$0")"
dir="$PWD"
sed -e "s|__USER__|$(id -un)|" -e "s|__DIR__|${dir}|" kora-backup.service \
  | sudo tee /etc/systemd/system/kora-backup.service > /dev/null
sudo cp kora-backup.timer /etc/systemd/system/kora-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now kora-backup.timer
systemctl list-timers kora-backup.timer --no-pager
echo "Sauvegarde quotidienne installée. Journal : journalctl -u kora-backup.service"
