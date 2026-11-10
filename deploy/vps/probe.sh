#!/usr/bin/env bash
# Sonde externe (KF-12) : interroge https://<domaine>/health/ready — la chaîne
# complète HTTPS → Caddy → API → PostgreSQL/Redis, certificat TLS inclus, depuis
# l'hôte (hors réseau Docker). La route Caddy /health/* expose uniquement les sondes
# (statut ok|erreur, aucune donnée métier).
# Deux échecs consécutifs : code de sortie 1 → OnFailure= déclenche l'alerte
# (anti-tempête centralisée dans alert.sh). Une sonde réussie remet le compteur à zéro.
set -euo pipefail
cd "$(dirname "$0")"

# Cible lue depuis .env sans l'exécuter (des valeurs contiennent des espaces).
public=$(grep -E '^KORA_PUBLIC_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
domain=$(grep -E '^KORA_DOMAIN=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
base="${public:-}"
if [[ -z "${base}" && -n "${domain}" ]]; then
  base="https://${domain}"
fi
if [[ -z "${base}" ]]; then
  echo "Cible de la sonde inconnue : définissez KORA_DOMAIN dans deploy/vps/.env." >&2
  exit 2
fi
url="${base%/}/health/ready"

state="backups/sonde-etat"
mkdir -p backups
chmod 700 backups

failures=0
if [[ -f "${state}" ]]; then
  failures=$(cat "${state}" 2>/dev/null || echo 0)
fi

if curl -fsS --max-time 15 "${url}" | grep -q '"status":"ok"'; then
  if (( failures > 0 )); then
    echo "Sonde : ${url} de nouveau OK (après ${failures} échec(s))."
  else
    echo "Sonde : ${url} OK"
  fi
  rm -f "${state}"
  exit 0
fi

failures=$((failures + 1))
printf '%s' "${failures}" > "${state}"
echo "Sonde : ${url} en échec (${failures} consécutif(s))."
if (( failures >= 2 )); then
  exit 1
fi
exit 0
