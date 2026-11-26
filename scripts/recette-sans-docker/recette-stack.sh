#!/usr/bin/env bash
# Pile de recette locale de kora-finance SANS Docker :
#   PostgreSQL (pgserver) :54330, Redis (fakeredis) :63790, S3 (moto) :9000.
#   Emails : backend « disabled » côté API (aucun SMTP requis pour la recette).
#
# Le script est idempotent : réexécutable, il ne (re)crée que ce qui manque.
# Aucun secret : le JWT et la clé Fernet sont générés par recette-env.sh.
#
# Usage :
#   ./recette-stack.sh                       # démarre la pile
#   RECETTE_DIR=/chemin ./recette-stack.sh   # répertoire de travail (défaut: ../.recette)
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
RECETTE_DIR=${RECETTE_DIR:-$(dirname "$REPO")/.recette}
TS="$RECETTE_DIR"
PGDATA=$TS/pgdata

mkdir -p "$TS"

# 1) Venv + dépendances (le venv survit aux redémarrages mais son interpréteur
#    peut disparaître : on teste réellement avant de réutiliser).
if [ ! -x "$TS/.venv/bin/python" ] || ! "$TS/.venv/bin/python" -c "import sys" 2>/dev/null; then
  rm -rf "$TS/.venv"
  python3 -m venv "$TS/.venv"
  "$TS/.venv/bin/pip" -q install --upgrade pip
fi
NEED_INSTALL=0
"$TS/.venv/bin/python" - <<'EOF' || NEED_INSTALL=1
import importlib.util as u
missing = [m for m in ("pgserver", "fakeredis", "moto") if u.find_spec(m) is None]
raise SystemExit(f"MISSING:{','.join(missing)}" if missing else "OK")
EOF
if [ "$NEED_INSTALL" = "1" ]; then
  "$TS/.venv/bin/pip" -q install pgserver fakeredis 'moto[server]'
fi

PGHOME=$("$TS/.venv/bin/python" -c "import pgserver, os; print(os.path.join(os.path.dirname(pgserver.__file__), 'pginstall'))")

# 2) Extensions contrib (btree_gist requis par les contraintes d'exclusion :
#    verrous d'exercice KF-03, lettrage, etc.). Selon la disposition du paquet
#    pgserver, les fichiers peuvent être au mauvais endroit : on les cherche.
if [ ! -f "$PGHOME/lib/postgresql/btree_gist.so" ]; then
  FOUND_SO=$(find "$PGHOME" -name "btree_gist*.so" 2>/dev/null | head -1 || true)
  if [ -n "$FOUND_SO" ]; then
    mkdir -p "$PGHOME/lib/postgresql"
    cp -f "$FOUND_SO" "$PGHOME/lib/postgresql/"
    SHARE_SRC=$(dirname "$(find "$PGHOME" -name "btree_gist.control" 2>/dev/null | head -1)" 2>/dev/null || true)
    if [ -n "${SHARE_SRC:-}" ] && [ -f "$SHARE_SRC/btree_gist.control" ]; then
      mkdir -p "$PGHOME/share/postgresql/extension"
      cp -f "$SHARE_SRC/btree_gist"* "$PGHOME/share/postgresql/extension/"
    fi
    echo "   btree_gist restauré depuis le paquet pgserver"
  else
    echo "ATTENTION: btree_gist.so introuvable dans pgserver — CREATE EXTENSION échouera"
  fi
fi

# 3) Cluster PostgreSQL
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"
  "$PGHOME/bin/initdb" -D "$PGDATA" -U kora_admin --auth=trust -E UTF8 >/dev/null
  echo "   cluster initialisé"
fi
# Les répertoires runtime vides sont parfois perdus lors d'une copie du PGDATA :
# PostgreSQL refuse de démarrer sans eux.
for d in pg_notify pg_tblspc pg_replslot pg_twophase pg_commit_ts pg_snapshots \
         pg_serial pg_stat pg_stat_tmp pg_subtrans pg_wal/archive_status log; do
  mkdir -p "$PGDATA/$d"; chmod 700 "$PGDATA/$d"
done
mkdir -p "$PGDATA/pg_multixact/members" "$PGDATA/pg_multixact/offsets"
chmod -R 700 "$PGDATA/pg_multixact"
chmod 700 "$PGDATA"

if ! (echo > /dev/tcp/127.0.0.1/54330) >/dev/null 2>&1; then
  rm -f "$PGDATA/postmaster.pid"
  setsid sh -c "nohup $PGHOME/bin/postgres -D $PGDATA -h 127.0.0.1 -p 54330 -k /tmp > $TS/pg.log 2>&1 < /dev/null &"
  for i in $(seq 1 60); do
    (echo > /dev/tcp/127.0.0.1/54330) >/dev/null 2>&1 || { sleep 1; continue; }
    # Le port peut répondre pendant la reprise WAL : attendre un vrai SELECT.
    if "$PGHOME/bin/psql" -h 127.0.0.1 -p 54330 -U kora_admin -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
"$PGHOME/bin/psql" -h 127.0.0.1 -p 54330 -U kora_admin -d postgres -tAc "SELECT 1" >/dev/null || {
  echo "ERREUR: postgres ne démarre pas"; tail -20 "$TS/pg.log"; exit 1; }

PSQL="$PGHOME/bin/psql -h 127.0.0.1 -p 54330 -U kora_admin -d postgres -tAc"
$PSQL "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kora_owner') THEN CREATE ROLE kora_owner LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS PASSWORD 'kora_owner_local'; ELSE ALTER ROLE kora_owner PASSWORD 'kora_owner_local'; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kora_app') THEN CREATE ROLE kora_app LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS NOINHERIT PASSWORD 'kora_app_local'; ELSE ALTER ROLE kora_app PASSWORD 'kora_app_local'; END IF; END \$\$;"
$PSQL "SELECT 1 FROM pg_database WHERE datname='kora_test'" | grep -q 1 || \
  $PSQL "CREATE DATABASE kora_test OWNER kora_owner"

# Droits du rôle runtime (équivalent init-roles.sh : l'app ne doit jamais être
# propriétaire des tables, cf. test_db_roles.py).
PGOWN="$PGHOME/bin/psql -h 127.0.0.1 -p 54330 -U kora_admin -d kora_test -tAc"
if ! $PGOWN "SELECT count(*) FROM pg_extension WHERE extname='btree_gist'" | grep -q 1; then
  $PGOWN "CREATE EXTENSION IF NOT EXISTS btree_gist"
fi
$PGOWN "ALTER SCHEMA public OWNER TO kora_owner; REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO kora_app;"
$PGOWN "GRANT CONNECT, TEMPORARY ON DATABASE kora_test TO kora_app;"
$PGOWN "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kora_app; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kora_app; GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO kora_app;"
$PGOWN "ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kora_app; ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kora_app; ALTER DEFAULT PRIVILEGES FOR ROLE kora_owner IN SCHEMA public GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO kora_app;"
echo "   postgres OK (54330) + rôles + droits"

# 4) Redis (fakeredis)
if ! (echo > /dev/tcp/127.0.0.1/63790) >/dev/null 2>&1; then
  setsid sh -c "nohup $TS/.venv/bin/python -c \"from fakeredis import TcpFakeServer as S; S(('127.0.0.1', 63790)).serve_forever()\" > $TS/redis.log 2>&1 < /dev/null &"
  sleep 2
fi
(echo > /dev/tcp/127.0.0.1/63790) >/dev/null 2>&1 && echo "   redis OK (63790)" || { echo "ERREUR redis"; exit 1; }

# 5) S3 (moto) + buckets. Deux buckets distincts : pièces applicatives (kora-test)
#    et sauvegardes (kora-backups), l'isolation des exercices de restauration
#    l'exige (cf. test_backup.py / restore-drill).
if ! (echo > /dev/tcp/127.0.0.1/9000) >/dev/null 2>&1; then
  setsid sh -c "nohup $TS/.venv/bin/moto_server -H 127.0.0.1 -p 9000 > $TS/s3.log 2>&1 < /dev/null &"
  sleep 2
fi
(echo > /dev/tcp/127.0.0.1/9000) >/dev/null 2>&1 || { echo "ERREUR S3"; exit 1; }
$TS/.venv/bin/python - <<'EOF'
import boto3
from botocore.client import Config
c = boto3.client("s3", endpoint_url="http://127.0.0.1:9000",
                 aws_access_key_id="kora-local", aws_secret_access_key="kora-local-secret",
                 region_name="garage", config=Config(signature_version="s3v4"))
def ensure(name):
    if name not in [b["Name"] for b in c.list_buckets()["Buckets"]]:
        try:
            c.create_bucket(Bucket=name)
        except Exception:
            c.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": "garage"})
for b in ("kora", "kora-test", "kora-backups"):
    ensure(b)
print("   buckets kora / kora-test / kora-backups prêts")
EOF
echo "PILE RECETTE OK"
