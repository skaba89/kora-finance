#!/usr/bin/env bash
# Déploie (ou met à jour) Kora depuis main, version par version (KF-11) :
#   1. pré-vols : .env complet, branche main, copie git propre, avance ff-only ;
#   2. release : images construites et étiquetées par le SHA court du commit
#      (KORA_IMAGE_TAG) — l'alias :prod n'est plus écrasé avant la bascule ;
#   3. sauvegarde pré-migration VÉRIFIÉE imposée (backup.sh : dump relu et déchiffré) ;
#   4. bascule : migrations (service migrate) puis `up -d --wait` (healthchecks) ;
#      en cas d'échec, retour automatique à la version précédente connue ;
#   5. consignation dans deploy/vps/releases.log (SHA, IDs d'images, date).
# Les données (volumes) ne sont jamais supprimées. Retour manuel : ./rollback.sh.
# CI préalable : la protection de branche main n'accepte qu'une PR verte, et le
# déploiement avance toujours sur origin/main (ff-only) — le commit déployé est
# donc exactement un commit validé par la CI.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]] || grep -qE '=__A_REMPLIR__$' .env; then
  echo "deploy/vps/.env absent ou incomplet : lancer ./init-env.sh et le compléter." >&2
  exit 1
fi

repo=../..
branch=$(git -C "${repo}" rev-parse --abbrev-ref HEAD)
if [[ "${branch}" != "main" ]]; then
  echo "Copie sur la branche « ${branch} » : la production se déploie uniquement depuis main." >&2
  exit 1
fi

# Copie propre : aucune modification suivie non commitée (les fichiers locaux non
# suivis — .env, backups/, releases.log… — sont ignorés, ils ne changent pas le code).
if [[ -n "$(git -C "${repo}" status --porcelain --untracked-files=no)" ]]; then
  echo "Copie git non propre : committer ou annuler les modifications avant de déployer." >&2
  exit 1
fi

if [[ "${1:-}" != "--sans-git" ]]; then
  git -C "${repo}" fetch --quiet origin main
  git -C "${repo}" merge --ff-only --quiet origin/main
fi
release=$(git -C "${repo}" rev-parse --short=12 HEAD)
echo "Version : $(git -C "${repo}" log -1 --format='%h %s')"
echo "Release : ${release}"

# Mode proxy commun : réseau « edge » partagé avec le proxy du serveur.
if grep -qE '^COMPOSE_FILE=.*proxy-externe' .env && ! docker network inspect edge > /dev/null 2>&1; then
  docker network create edge > /dev/null
  echo "Réseau edge créé : y raccorder le proxy du serveur (docs/DEPLOIEMENT.md)."
fi

# Version actuellement déployée (cible du retour arrière), vide en première install.
previous=$(cat .release 2>/dev/null || true)

# 1. Build étiqueté : les images immuables kora-api:<release> / kora-web:<release> sont
#    créées sans toucher à la pile en place ni à l'alias :prod (fallback hors deploy.sh).
export KORA_IMAGE_TAG="${release}"
docker compose build --pull

# Vérifie le stockage S3 avec la NOUVELLE version, avant de remplacer quoi que ce soit
# (clé, bucket, https).
docker compose run --rm --no-deps api python -m kora.scripts.check_storage

# 2. Sauvegarde pré-migration VÉRIFIÉE : le dump est relu et déchiffré par backup.sh,
#    qui échoue (et interrompt le déploiement) si la copie distante n'est pas fidèle.
#    Elle part avec l'IMAGE EN COURS (previous), pas avec celle qu'on vient de construire.
#    Première installation (postgres absent) : aucune donnée existante, on passe avec
#    un avertissement explicite.
if [[ -n "$(docker compose ps -q postgres 2>/dev/null)" ]] \
  && docker compose exec -T postgres pg_isready -U kora_admin -d kora > /dev/null 2>&1; then
  echo "Sauvegarde pré-migration (vérifiée)…"
  KORA_IMAGE_TAG="${previous:-prod}" ./backup.sh
else
  # Échec fermé : une panne PostgreSQL n'est JAMAIS la preuve d'une base vide.
  # La première installation exige un opt-in explicite ET aucune trace d'installation.
  # Ne pas utiliser --sans-git pour contourner ce contrôle.
  if [[ "${KORA_ALLOW_INITIAL_INSTALL:-0}" == "1" ]] \
    && [[ ! -s .release ]] \
    && [[ ! -s releases.log ]] \
    && [[ -z "$(docker compose ps -aq postgres 2>/dev/null)" ]] \
    && ! docker volume inspect kora_postgres_data >/dev/null 2>&1; then
    echo "Première installation explicitement autorisée : aucune base ni volume existant."
  else
    echo "BLOCAGE : PostgreSQL indisponible ou déjà initialisé ; sauvegarde obligatoire." >&2
    echo "Vérifier la base et restaurer son fonctionnement avant de déployer." >&2
    echo "Première installation neuve uniquement : KORA_ALLOW_INITIAL_INSTALL=1 ./deploy.sh" >&2
    exit 1
  fi
fi

# 3. Bascule : migrations puis attente des healthchecks. En cas d'échec (migration
#    refusée, build indisponible, healthcheck), retour automatique à la version
#    précédente. Le schéma n'est jamais migré en arrière (convention expand/contract,
#    docs/DEPLOIEMENT.md §4) : les volumes restent intacts.
if ! docker compose up -d --wait --remove-orphans; then
  echo "ÉCHEC du déploiement (migrations ou healthcheck) : tentative de retour à la version précédente." >&2
  if [[ -n "${previous}" ]]; then
    KORA_IMAGE_TAG="${previous}" docker compose up -d --wait --remove-orphans || true
  fi
  docker compose ps --format 'table {{.Service}}\t{{.Status}}' || true
  echo "Diagnostiquer : docker compose logs --tail=200 migrate api." >&2
  echo "Consulter releases.log pour les versions connues ; ./rollback.sh si nécessaire." >&2
  exit 1
fi

# 4. Consignation de la release : SHA, IDs d'images (digests locaux), date.
api_id=$(docker image inspect --format '{{.Id}}' "kora-api:${release}")
web_id=$(docker image inspect --format '{{.Id}}' "kora-web:${release}")
printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${release}" "${api_id}" "${web_id}" >> releases.log
echo "${release}" > .release
echo "${previous:-${release}}" > .previous-release

# 5. Ne garder que les cinq dernières releases : les images plus anciennes sont
#    retirées (les cinq dernières restent disponibles pour rollback.sh).
if [[ "$(wc -l < releases.log)" -gt 5 ]]; then
  cut -f2 releases.log | tail -5 > .releases-keep
  while read -r old; do
    grep -qxF "${old}" .releases-keep || { docker image rm "kora-api:${old}" "kora-web:${old}" > /dev/null 2>&1 || true; }
  done < <(cut -f2 releases.log | head -n -5)
  rm -f .releases-keep
fi

docker compose ps --format 'table {{.Service}}\t{{.Status}}'
echo "Kora ${release} en ligne : https://$(grep -E '^KORA_DOMAIN=' .env | cut -d= -f2)"
echo "Retour arrière : ./rollback.sh (revient à « ${previous:-aucune version antérieure} »)."
