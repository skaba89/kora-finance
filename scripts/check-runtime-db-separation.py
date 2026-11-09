"""Vérifie les environnements Compose résolus sans démarrer aucun service.

Les valeurs sont synthétiques ; la configuration et les secrets ne sont jamais affichés.
Exécuté par la CI hôte (Docker Compose), avant les tests applicatifs.
"""

import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "KORA_DATABASE_MIGRATION_URL",
    "KORA_DB_OWNER_PASSWORD",
    "KORA_POSTGRES_ADMIN_PASSWORD",
}


def check(files: list[str]) -> None:
    env = {
        **os.environ,
        **{
            name: secrets.token_hex(32)
            for name in (
                "KORA_POSTGRES_ADMIN_PASSWORD",
                "KORA_DB_OWNER_PASSWORD",
                "KORA_DB_APP_PASSWORD",
                "KORA_JWT_SECRET",
                "KORA_GARAGE_RPC_SECRET",
                "KORA_GARAGE_ADMIN_TOKEN",
                "KORA_S3_SECRET_ACCESS_KEY",
                "KORA_BACKUP_S3_SECRET_ACCESS_KEY",
            )
        },
        "KORA_ENCRYPTION_KEYS": "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
        "KORA_S3_ACCESS_KEY_ID": "synthetic-test-only",
        "KORA_S3_ENDPOINT_URL": "https://storage.invalid",
        "KORA_S3_REGION": "test",
        "KORA_S3_BUCKET": "test-only",
        # Sauvegardes : bucket et clé dédiés (KF-09), distincts du stockage des pièces.
        "KORA_BACKUP_S3_ACCESS_KEY_ID": "synthetic-test-only",
        "KORA_BACKUP_S3_ENDPOINT_URL": "https://storage.invalid",
        "KORA_BACKUP_S3_REGION": "test",
        "KORA_BACKUP_S3_BUCKET": "test-backups-only",
        "KORA_DOMAIN": "kora.invalid",
        "KORA_ACME_EMAIL": "audit@example.invalid",
        "COMPOSE_PROFILES": "",
    }
    args = ["docker", "compose", "--env-file", "/dev/null"]
    for file in files:
        args.extend(["-f", file])
    result = subprocess.run(  # noqa: S603 (commande fixe, fichiers internes au dépôt)
        [*args, "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit("Impossible de résoudre la configuration Compose de test.")
    services = json.loads(result.stdout)["services"]
    for name in ("api", "worker"):
        leaked = FORBIDDEN.intersection(services[name]["environment"])
        if leaked:
            raise SystemExit(
                f"Service {name} : identifiant privilégié présent dans l'environnement."
            )
    if set(services["migrate"]["environment"]) != {"KORA_DATABASE_MIGRATION_URL"}:
        raise SystemExit("Le service migrate doit recevoir seulement son URL dédiée.")
    print("Séparation runtime/migration vérifiée : " + ", ".join(files))


if __name__ == "__main__":
    check(["docker-compose.yml"])
    check(["deploy/vps/compose.yml"])
    check(["deploy/vps/compose.yml", "deploy/vps/compose.proxy-externe.yml"])
