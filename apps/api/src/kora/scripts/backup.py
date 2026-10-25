"""Sauvegardes chiffrées de la base vers le stockage S3 (préfixe `backups/`).

Le fichier de sauvegarde (produit par `pg_dump -Fc`, voir deploy/vps/backup.sh) est
chiffré comme les pièces justificatives (AES-256-GCM, clé propre au fichier enveloppée
par KORA_ENCRYPTION_KEYS), relu et vérifié après l'envoi. Sans KORA_ENCRYPTION_KEYS, une
sauvegarde est illisible : ces clés doivent être conservées hors du serveur.

    python -m kora.scripts.backup upload /backups/kora-20261025T023000Z.dump
    python -m kora.scripts.backup list
    python -m kora.scripts.backup download backups/kora-….dump.enc /backups/restaure.dump
    python -m kora.scripts.backup prune --keep-days 30

Limite : le fichier est traité en mémoire (adapté jusqu'à quelques centaines de Mo).
"""

import argparse
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kora.core.config import get_settings
from kora.storage import objects

PREFIX = "backups/"
_MAGIC = b"KORA-BKP1"
# Sauvegardes toujours conservées, quel que soit leur âge.
_KEEP_AT_LEAST = 7
MAX_BYTES = 2 * 1024**3


def object_key(filename: str) -> str:
    return f"{PREFIX}{filename}.enc"


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
    content = path.read_bytes()
    if not content:
        raise SystemExit(f"Sauvegarde vide : {path}")
    if len(content) > MAX_BYTES:
        raise SystemExit("Sauvegarde trop volumineuse pour un traitement en mémoire.")
    key = object_key(path.name)
    sealed = objects.seal(content, key)
    objects._client().put_object(
        Bucket=get_settings().s3_bucket,
        Key=key,
        Body=pack(sealed),
        ContentType="application/octet-stream",
    )
    # Relecture : une sauvegarde n'est comptée que si elle se déchiffre à l'identique.
    restored = download_bytes(key)
    if hashlib.sha256(restored).digest() != hashlib.sha256(content).digest():
        raise SystemExit(f"Vérification échouée pour {key} : la copie distante diffère.")
    return key


def download_bytes(key: str) -> bytes:
    sealed = unpack(objects.get(key))
    return objects.unseal(sealed.blob, sealed.wrapped_key, key)


def list_backups() -> list[tuple[str, datetime, int]]:
    client = objects._client()
    bucket = get_settings().s3_bucket
    found: list[tuple[str, datetime, int]] = []
    token: str | None = None
    while True:
        kwargs = {
            "Bucket": bucket,
            "Prefix": PREFIX,
            **({"ContinuationToken": token} if token else {}),
        }
        page = client.list_objects_v2(**kwargs)  # type: ignore[arg-type]
        found.extend((o["Key"], o["LastModified"], o["Size"]) for o in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return sorted(found, key=lambda item: (item[1], item[0]))
        token = page["NextContinuationToken"]


def prune(keep_days: int, now: datetime | None = None) -> list[str]:
    """Supprime les sauvegardes plus anciennes que `keep_days`, en gardant toujours les
    sept plus récentes (une panne prolongée ne doit pas tout effacer)."""
    backups = list_backups()
    limit = (now or datetime.now(UTC)) - timedelta(days=keep_days)
    candidates = backups[:-_KEEP_AT_LEAST] if len(backups) > _KEEP_AT_LEAST else []
    removed = [key for key, modified, _ in candidates if modified < limit]
    for key in removed:
        objects.delete(key)
    return removed


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
    args = parser.parse_args(argv)

    if args.command == "upload":
        print(f"Sauvegarde envoyée et vérifiée : {upload(args.path)}")
    elif args.command == "list":
        for key, modified, size in list_backups():
            print(f"{modified:%Y-%m-%d %H:%M} UTC  {size:>12} octets  {key}")
    elif args.command == "download":
        args.path.write_bytes(download_bytes(args.key))
        print(f"Sauvegarde déchiffrée : {args.path}")
    elif args.command == "prune":
        removed = prune(args.keep_days)
        print(f"{len(removed)} sauvegarde(s) supprimée(s) (plus de {args.keep_days} jours).")
    sys.exit(0)


if __name__ == "__main__":
    main()
