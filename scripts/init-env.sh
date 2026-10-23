#!/usr/bin/env bash
# Crée .env à partir de .env.example avec des secrets aléatoires. Ne touche jamais un .env existant.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
  echo ".env existe déjà : rien à faire." >&2
  exit 0
fi
umask 077
while IFS= read -r line; do
  if [[ "$line" == *"=__GENERATE__" ]]; then
    printf '%s=%s\n' "${line%%=*}" "$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  else
    printf '%s\n' "$line"
  fi
done < .env.example > .env
echo ".env créé avec des secrets aléatoires (permissions 600)."
