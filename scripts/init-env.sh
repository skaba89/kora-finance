#!/usr/bin/env bash
# Crée .env à partir de .env.example avec des secrets aléatoires. Si .env existe, n'y
# ajoute que les variables nouvelles du modèle : les valeurs existantes ne changent jamais.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

render() {
  local line="$1"
  if [[ "$line" == *"=__GENERATE__" ]]; then
    printf '%s=%s\n' "${line%%=*}" "$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  elif [[ "$line" == *"=__GENERATE_FERNET__" ]]; then
    # Clé Fernet : 32 octets aléatoires en base64 url-safe.
    printf '%s=%s\n' "${line%%=*}" "$(head -c32 /dev/urandom | base64 | tr '+/' '-_')"
  elif [[ "$line" == *"=__GENERATE_GARAGE_KEY_ID__" ]]; then
    printf '%s=GK%s\n' "${line%%=*}" "$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')"
  else
    printf '%s\n' "$line"
  fi
}

if [[ ! -e .env ]]; then
  while IFS= read -r line; do render "$line"; done < .env.example > .env
  echo ".env créé avec des secrets aléatoires (permissions 600)."
  exit 0
fi

added=()
while IFS= read -r line; do
  [[ "$line" =~ ^([A-Z0-9_]+)= ]] || continue
  name="${BASH_REMATCH[1]}"
  if ! grep -q "^${name}=" .env; then
    render "$line" >> .env
    added+=("$name")
  fi
done < .env.example
if ((${#added[@]})); then
  echo ".env complété : ${added[*]}" >&2
else
  echo ".env existe déjà et est complet : rien à faire." >&2
fi
