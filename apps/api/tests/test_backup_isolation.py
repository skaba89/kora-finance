"""Isolation des identifiants de sauvegarde (KF-09), vérifiée mécaniquement.

Aucune composition ne doit transmettre KORA_BACKUP_S3_* aux services applicatifs
(api, worker, migrate, web) ni à l'ancrage d'environnement partagé `x-api-env` — une
variable ajoutée à l'ancrage atteindrait api ET worker d'un coup. Le service `backup`
ne doit recevoir ni les variables du stockage des pièces (KORA_S3_*) ni la clé
d'administration (elle ne vit que dans le gestionnaire de secrets, hors serveur).
Les scripts de sauvegarde/restauration doivent passer par le service `backup` sous
profil, et backup.sh ne doit plus purger (rétention administrée côté fournisseur).
"""

import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from kora.core.config import BackupSettings, Settings

REPO = Path(__file__).resolve().parents[3]

# Services dont les conteneurs ne doivent JAMAIS voir les identifiants de sauvegarde.
SERVICES_APPLICATIFS = ("api", "worker", "migrate", "web")


def _service_block(text: str, name: str) -> str:
    """Bloc YAML du service `name` (indentation deux espaces) jusqu'au service suivant."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"{name}:" and line.startswith("  ") and not line.startswith("   "):
            start = index + 1
            break
    assert start is not None, f"service « {name} » introuvable dans la composition"
    block: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith("    ") and line.strip():
            break  # service suivant ou clé de premier rang
        block.append(line)
    return "\n".join(block)


def _anchor_block(text: str, name: str) -> str:
    """Bloc d'un ancrage YAML de premier rang (ex. « x-api-env: &api-env »)."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"{name}:"):
            start = index + 1
            break
    assert start is not None, f"ancrage « {name} » introuvable"
    block: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        block.append(line)
    return "\n".join(block)


def _assert_isolation(compose: Path) -> None:
    text = compose.read_text()
    for service in SERVICES_APPLICATIFS:
        assert "KORA_BACKUP" not in _service_block(text, service), (
            f"{compose.name} : le service « {service} » ne doit pas recevoir "
            "d'identifiants de sauvegarde (KF-09)"
        )
    assert "KORA_BACKUP" not in _anchor_block(text, "x-api-env"), (
        f"{compose.name} : l'ancrage x-api-env (api ET worker) ne doit pas recevoir "
        "d'identifiants de sauvegarde (KF-09)"
    )
    # Environnement effectif du service « backup » : son bloc, complété de son ancre
    # (compose local : les variables vivent dans x-backup-env).
    backup_env = _service_block(text, "backup")
    if "x-backup-env:" in text:
        backup_env += _anchor_block(text, "x-backup-env")
    assert "KORA_ENCRYPTION_KEYS:" in backup_env
    assert "KORA_BACKUP_S3_BUCKET" in backup_env, (
        f"{compose.name} : le service « backup » doit porter les variables dédiées"
    )
    assert "KORA_S3_BUCKET:" not in backup_env.replace("KORA_BACKUP_S3_BUCKET:", ""), (
        f"{compose.name} : le service « backup » ne doit pas recevoir "
        "les identifiants du stockage des pièces"
    )
    # Toute occurrence de KORA_BACKUP du fichier est confinée à l'environnement du
    # service « backup » et au service d'initialisation du stockage (storage-init
    # crée le bucket et la clé de sauvegarde : outillage d'infrastructure, pas
    # l'application).
    confine = backup_env
    if "  storage-init:" in text:
        confine += _service_block(text, "storage-init")
    assert text.count("KORA_BACKUP") == confine.count("KORA_BACKUP"), (
        f"{compose.name} : des identifiants de sauvegarde apparaissent hors du "
        "service « backup » (KF-09)"
    )


def test_compose_local_isole_les_sauvegardes() -> None:
    _assert_isolation(REPO / "docker-compose.yml")


def test_compose_vps_isole_les_sauvegardes() -> None:
    _assert_isolation(REPO / "deploy" / "vps" / "compose.yml")


def test_proxy_externe_sans_identifiant_sauvegarde() -> None:
    compose = REPO / "deploy" / "vps" / "compose.proxy-externe.yml"
    text = compose.read_text()
    if "KORA_BACKUP" in text:
        _assert_isolation(compose)


def test_scripts_passent_par_le_service_backup() -> None:
    for script in ("backup.sh", "restore.sh"):
        text = (REPO / "deploy" / "vps" / script).read_text()
        assert "--profile backup" in text, f"{script} doit activer le profil backup"
        assert "backup python -m kora.scripts.backup" in text, (
            f"{script} doit exécuter le module de sauvegarde dans le service « backup »"
        )
    backup_sh = (REPO / "deploy" / "vps" / "backup.sh").read_text()
    # La purge ne doit plus être appelée : la rétention est administrée côté fournisseur
    # et la purge manuelle exige la clé d'administration hors VPS (KF-09).
    executable = [
        line
        for line in backup_sh.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any("prune" in line for line in executable), (
        "backup.sh ne doit plus purger : la rétention est administrée côté fournisseur "
        "et la purge manuelle exige la clé d'administration hors VPS (KF-09)"
    )


def test_modeles_env_portent_le_bucket_dedie() -> None:
    vps = (REPO / "deploy" / "vps" / "env.example").read_text()
    assert "KORA_BACKUP_S3_BUCKET=" in vps
    assert "KORA_BACKUP_ADMIN_S3_ACCESS_KEY_ID=" in vps  # documentée, commentée
    local = (REPO / ".env.example").read_text()
    assert "KORA_BACKUP_S3_ACCESS_KEY_ID=" in local


def test_la_configuration_runtime_ne_lit_pas_les_identifiants_sauvegarde() -> None:
    """Préfixes d'environnement disjoints : la configuration de l'API (KORA_*) ne peut
    pas lire une variable de sauvegarde (KORA_BACKUP_S3_*), et réciproquement."""
    assert BackupSettings.model_config["env_prefix"] == "KORA_BACKUP_S3_"
    assert not any("backup" in field for field in Settings.model_fields)
    assert not any(field.startswith("s3_") and "backup" in field for field in Settings.model_fields)


def test_chiffrement_sans_configuration_runtime() -> None:
    """Reproduit le conteneur backup : aucun secret runtime hormis le chiffrement."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("KORA_")}
    env.update(KORA_ENV="production", KORA_ENCRYPTION_KEYS=Fernet.generate_key().decode())
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from kora.storage import objects; "
            "sealed = objects.seal(b'PGDMP', 'backups/test.dump.enc'); "
            "assert objects.unseal(sealed.blob, sealed.wrapped_key, "
            "'backups/test.dump.enc') == b'PGDMP'",
        ],
        env=env,
        check=True,
    )
