#!/usr/bin/env bash
# Contrôle de fraîcheur (KF-12) : la sauvegarde la plus récente du bucket dédié doit
# dater de moins de 26 h (sauvegarde quotidienne 02:30 UTC + marge d'aléas). Exécuté
# quotidiennement par kora-freshness.timer ; en échec, OnFailure= déclenche l'alerte.
set -euo pipefail
cd "$(dirname "$0")"
export KORA_IMAGE_TAG="${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}"
docker compose --profile backup run --rm --no-deps backup \
  python -m kora.scripts.backup status --max-age-hours 26
