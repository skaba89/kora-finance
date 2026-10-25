#!/usr/bin/env bash
# Préparation d'un VPS Ubuntu 24.04 neuf pour Kora (à lancer UNE fois, avec sudo) :
# mises à jour, Docker (dépôt officiel), pare-feu, mises à jour de sécurité automatiques,
# fail2ban (SSH), fichier d'échange pour les builds, durcissement SSH si une clé existe.
#
#   sudo ./deploy/vps/bootstrap-server.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "À lancer avec sudo." >&2
  exit 1
fi
admin_user="${SUDO_USER:-ubuntu}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Mises à jour du système"
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl git ufw unattended-upgrades fail2ban

echo "==> Docker (dépôt officiel docker.com)"
if ! command -v docker > /dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "${admin_user}"

echo "==> Pare-feu : SSH, HTTP, HTTPS uniquement"
# Docker contourne ufw pour les ports publiés : seul Caddy publie des ports (80/443),
# PostgreSQL, Redis et l'API ne sont jamais publiés (voir compose.yml).
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Mises à jour de sécurité automatiques"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades fail2ban

echo "==> Fichier d'échange (build du frontend sur un serveur de 4 Go)"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile > /dev/null
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> SSH"
keys="/home/${admin_user}/.ssh/authorized_keys"
if [[ -s "${keys}" ]]; then
  cat > /etc/ssh/sshd_config.d/10-kora.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
  systemctl reload ssh
  echo "Connexion SSH par clé uniquement (mot de passe désactivé)."
else
  echo "ATTENTION : aucune clé SSH pour ${admin_user} ; connexion par mot de passe laissée active."
  echo "Ajoutez votre clé (ssh-copy-id) puis relancez ce script pour la désactiver."
fi

echo
echo "Serveur prêt. Déconnectez-vous puis reconnectez-vous (groupe docker), puis suivez"
echo "docs/DEPLOIEMENT.md (étape « Installer Kora »)."
