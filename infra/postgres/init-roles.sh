#!/usr/bin/env bash
# Crée les rôles et bases de Kora. Idempotent.
#  - kora_owner : propriétaire des bases et du schéma, exécute les migrations Alembic.
#  - kora_app   : rôle d'exécution de l'API et du worker. NOSUPERUSER, NOBYPASSRLS,
#                 aucun droit DDL : uniquement SELECT/INSERT/UPDATE/DELETE.
# Exécuté automatiquement par l'image postgres (docker-entrypoint-initdb.d) en local,
# et explicitement par la CI. Mots de passe lus depuis l'environnement, jamais en dur.
set -euo pipefail

: "${KORA_DB_OWNER_PASSWORD:?KORA_DB_OWNER_PASSWORD manquant}"
: "${KORA_DB_APP_PASSWORD:?KORA_DB_APP_PASSWORD manquant}"
DATABASES="${KORA_DATABASES:-kora kora_test}"

psql_admin() {
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --no-password "$@"
}

psql_admin --dbname postgres \
  -v owner_pw="${KORA_DB_OWNER_PASSWORD}" -v app_pw="${KORA_DB_APP_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE kora_owner LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS PASSWORD %L', :'owner_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_owner') \gexec
SELECT format('CREATE ROLE kora_app LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS NOINHERIT PASSWORD %L', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kora_app') \gexec
SQL

for db in ${DATABASES}; do
  psql_admin --dbname postgres -v db="${db}" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER kora_owner', :'db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO kora_app', :'db') \gexec
SQL
  psql_admin --dbname "${db}" <<'SQL'
ALTER SCHEMA public OWNER TO kora_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO kora_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO kora_app;
SQL
done
echo "init-roles : rôles et bases Kora prêts (${DATABASES})."
