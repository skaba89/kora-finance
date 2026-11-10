"""Sauvegardes chiffrées de la base vers un bucket S3 **dédié** (KF-09).

Le fichier de sauvegarde (produit par `pg_dump -Fc`, voir deploy/vps/backup.sh) est
chiffré comme les pièces justificatives (AES-256-GCM, clé propre au fichier enveloppée
par KORA_ENCRYPTION_KEYS), relu et vérifié après l'envoi. Sans KORA_ENCRYPTION_KEYS, une
sauvegarde est illisible : ces clés doivent être conservées hors du serveur.

Les sauvegardes n'utilisent ni le bucket ni la clé du stockage des pièces : bucket et
identifiants dédiés (KORA_BACKUP_S3_*), transmis par le Compose au seul service
`backup` — jamais à l'API ni au worker. La clé de sauvegarde ne doit porter **aucun
droit de suppression** (B2 : capabilities sans deleteFiles ; S3 : politique refusant
DeleteObject) : la rétention est administrée côté fournisseur (cycle de vie, Object
Lock), pas par l'application.

    python -m kora.scripts.backup upload /backups/kora-20261025T023000Z.dump
    python -m kora.scripts.backup list
    python -m kora.scripts.backup download backups/kora-….dump.enc /backups/restaure.dump
    python -m kora.scripts.backup status --max-age-hours 26   # fraîcheur (KF-12)

Purge manuelle (opération d'administration, depuis un poste hors VPS, avec la clé
distincte KORA_BACKUP_ADMIN_S3_* ; garde toujours les sept plus récentes) :

    python -m kora.scripts.backup prune --keep-days 30

Limite : le fichier est contrôlé par stat() avant toute lecture (KF-23) — un fichier
surdimensionné ou spécial est refusé sans charger un octet ; au-delà du plafond
(KORA_BACKUP_S3_MAX_BYTES, aligné sur le budget du conteneur « backup »), la
sauvegarde est refusée et le streaming S3 reste du travail futur.
"""

import argparse
import hashlib
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kora.core.config import get_backup_settings
from kora.storage import backups_store, objects

PREFIX = "backups/"
_MAGIC = b"KORA-BKP1"
# Sauvegardes toujours conservées, quel que soit leur âge.
_KEEP_AT_LEAST = 7


def object_key(filename: str) -> str:
    return f"{PREFIX}{filename}.enc"


def _check_key(key: str) -> None:
    """Le module ne gère que les objets du préfixe des sauvegardes (KF-23) : ni
    traversée de préfixe, ni clé hors bucket de sauvegardes."""
    if not key.startswith(PREFIX) or ".." in key or "//" in key:
        raise SystemExit(
            f"Clé de sauvegarde invalide : {key!r} (format attendu : {PREFIX}kora-….dump.enc)."
        )


def pack(sealed: objects.SealedObject) -> bytes:
    """Format : signature, longueur de la clé enveloppée (2 octets), clé, contenu chiffré."""
    return _MAGIC + len(sealed.wrapped_key).to_bytes(2, "big") + sealed.wrapped_key + sealed.blob


def unpack(data: bytes) -> objects.SealedObject:
    if not data.startswith(_MAGIC):
        raise objects.CorruptedObjectError("signature de sauvegarde absente")
    start = len(_MAGIC)
    size = int.from_bytes(data[start : start + 2], "big")
    wrapped = data[start + 2 : start + 2 + size]
    return objects.SealedObject(blob=data[start + 2 + size :], wrapped_key=wrapped)


def upload(path: Path) -> str:
    # KF-23 : contrôle AVANT lecture — stat() ne charge rien en mémoire, donc un
    # fichier de 50 Go (ou un fifo, un périphérique) est refusé sans saturer.
    infos = path.stat()
    if not stat.S_ISREG(infos.st_mode):
        raise SystemExit(f"Pas un fichier régulier : {path}")
    if infos.st_size == 0:
        raise SystemExit(f"Sauvegarde vide : {path}")
    limite = get_backup_settings().max_bytes
    if infos.st_size > limite:
        raise SystemExit(
            f"Sauvegarde trop volumineuse ({infos.st_size} octets, plafond {limite}) : "
            "augmentez KORA_BACKUP_S3_MAX_BYTES dans la limite du budget du conteneur."
        )
    content = path.read_bytes()
    key = object_key(path.name)
    sealed = objects.seal(content, key)
    backups_store.put(key, pack(sealed))
    # Relecture : une sauvegarde n'est comptée que si elle se déchiffre à l'identique.
    restored = download_bytes(key)
    if hashlib.sha256(restored).digest() != hashlib.sha256(content).digest():
        raise SystemExit(f"Vérification échouée pour {key} : la copie distante diffère.")
    return key


def download_bytes(key: str) -> bytes:
    _check_key(key)
    sealed = unpack(backups_store.get(key))
    return objects.unseal(sealed.blob, sealed.wrapped_key, key)


def download_to(key: str, path: Path) -> None:
    """Déchiffre vers `path` par écriture temporaire + renommage atomique (KF-23) :
    aucun fichier tronqué ne peut être confondu avec un dump restaurable."""
    if path.is_dir():
        raise SystemExit(f"La destination est un répertoire : {path}")
    content = download_bytes(key)
    partiel = path.with_name(path.name + ".partiel")
    partiel.write_bytes(content)
    os.replace(partiel, path)


def list_backups() -> list[tuple[str, datetime, int]]:
    found: list[tuple[str, datetime, int]] = [
        (key, modified, size) for key, modified, size in backups_store.list_prefix(PREFIX)
    ]
    return sorted(found, key=lambda item: (item[1], item[0]))


def prune(keep_days: int, now: datetime | None = None) -> list[str]:
    """Supprime, avec la clé d'administration distincte, les sauvegardes plus anciennes
    que `keep_days` en gardant toujours les sept plus récentes (une panne prolongée ne
    doit pas tout effacer). Refusée sans KORA_BACKUP_ADMIN_S3_* : la clé de sauvegarde
    quotidienne ne porte aucun droit de suppression (KF-09)."""
    admin = backups_store.admin_client()
    backups = list_backups()
    limit = (now or datetime.now(UTC)) - timedelta(days=keep_days)
    candidates = backups[:-_KEEP_AT_LEAST] if len(backups) > _KEEP_AT_LEAST else []
    removed = [key for key, modified, _ in candidates if modified < limit]
    for key in removed:
        # Idempotent : un objet absent n'est pas une erreur, comme en S3.
        admin.delete_object(Bucket=backups_store.bucket(), Key=key)
    return removed


def _now() -> datetime:
    """Heure courante (point d'injection pour les tests du contrôle de fraîcheur)."""
    return datetime.now(UTC)


def freshness(max_age_hours: int, now: datetime | None = None) -> tuple[bool, str]:
    """Contrôle de fraîcheur (KF-12) : la sauvegarde la plus récente doit dater de
    moins de `max_age_hours` heures — sinon la sauvegarde quotidienne ne tourne plus.
    Retourne (ok, message) ; aucun secret n'est affiché."""
    listed = list_backups()
    if not listed:
        return False, (
            "Aucune sauvegarde dans le bucket dédié : la sauvegarde quotidienne ne "
            "tourne plus (voir deploy/vps/kora-backup.timer)."
        )
    key, modified, _ = listed[-1]
    age = (now or _now()) - modified
    hours = age.total_seconds() / 3600
    if age > timedelta(hours=max_age_hours):
        return False, (
            f"Dernière sauvegarde trop ancienne : {key} ({hours:.1f} h, limite "
            f"{max_age_hours} h). La sauvegarde quotidienne ne tourne plus."
        )
    return True, f"Dernière sauvegarde : {key} ({hours:.1f} h)."


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kora.scripts.backup", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("upload").add_argument("path", type=Path)
    sub.add_parser("list")
    down = sub.add_parser("download")
    down.add_argument("key")
    down.add_argument("path", type=Path)
    pr = sub.add_parser("prune")
    pr.add_argument("--keep-days", type=int, default=30)
    st = sub.add_parser("status")
    st.add_argument("--max-age-hours", type=int, default=26)
    args = parser.parse_args(argv)

    if args.command == "upload":
        print(f"Sauvegarde envoyée et vérifiée : {upload(args.path)}")
    elif args.command == "list":
        for key, modified, size in list_backups():
            print(f"{modified:%Y-%m-%d %H:%M} UTC  {size:>12} octets  {key}")
    elif args.command == "download":
        download_to(args.key, args.path)
        print(f"Sauvegarde déchiffrée : {args.path}")
    elif args.command == "prune":
        removed = prune(args.keep_days)
        print(f"{len(removed)} sauvegarde(s) supprimée(s) (plus de {args.keep_days} jours).")
    elif args.command == "status":
        ok, message = freshness(args.max_age_hours)
        print(message)
        sys.exit(0 if ok else 1)
    sys.exit(0)


if __name__ == "__main__":
    main()
