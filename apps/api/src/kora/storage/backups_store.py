"""Stockage des sauvegardes : bucket et identifiants S3 **dédiés** (KF-09).

Les sauvegardes ne partagent rien avec le stockage des pièces justificatives
(`kora.storage.objects`) : autre bucket, autre clé d'accès, client boto3 distinct.
L'API et le worker ne reçoivent jamais ces identifiants (le Compose ne les transmet
qu'au service `backup`) : une application compromise peut détruire les pièces, pas
les sauvegardes.

Ce module n'expose volontairement **aucune suppression** avec la clé de sauvegarde :
la rétention est administrée côté fournisseur (cycle de vie, Object Lock). La purge
manuelle passe par la clé d'administration distincte `KORA_BACKUP_ADMIN_S3_*`
(`admin_client`), jamais déployée sur le serveur.
"""

from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from kora.core.config import get_backup_admin_settings, get_backup_settings
from kora.core.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

_UNAVAILABLE = "Le stockage des sauvegardes est momentanément indisponible. Réessayez plus tard."


@lru_cache
def _client() -> "S3Client":
    try:
        settings = get_backup_settings()
    except ValidationError as exc:
        raise SystemExit(
            "Identifiants de sauvegarde manquants : définissez KORA_BACKUP_S3_ENDPOINT_URL, "
            "KORA_BACKUP_S3_BUCKET, KORA_BACKUP_S3_ACCESS_KEY_ID et "
            "KORA_BACKUP_S3_SECRET_ACCESS_KEY (bucket et clé dédiés, distincts du stockage "
            "des pièces — KF-09)."
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key.get_secret_value(),
        config=Config(
            # Adressage par chemin : compatible avec tous les fournisseurs S3.
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=settings.timeout_seconds,
            retries={"max_attempts": 3, "mode": "standard"},
            # Sommes de contrôle étendues seulement si le service les exige (compatibilité).
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def bucket() -> str:
    return get_backup_settings().bucket


def put(object_key: str, body: bytes) -> None:
    try:
        _client().put_object(
            Bucket=bucket(),
            Key=object_key,
            Body=body,
            ContentType="application/octet-stream",
        )
    except (BotoCoreError, ClientError) as exc:
        raise ServiceUnavailableError(_UNAVAILABLE) from exc


def get(object_key: str) -> bytes:
    try:
        response = _client().get_object(Bucket=bucket(), Key=object_key)
        body: bytes = response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise ServiceUnavailableError(_UNAVAILABLE) from exc
    return body


def list_prefix(prefix: str) -> list[tuple[str, datetime, int]]:
    """Liste (clé, dernière modification, taille) sous `prefix`, pagination comprise."""
    found: list[tuple[str, datetime, int]] = []
    token: str | None = None
    while True:
        kwargs = {
            "Bucket": bucket(),
            "Prefix": prefix,
            **({"ContinuationToken": token} if token else {}),
        }
        page = _client().list_objects_v2(**kwargs)  # type: ignore[arg-type]
        found.extend((o["Key"], o["LastModified"], o["Size"]) for o in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return found
        token = page["NextContinuationToken"]


def admin_client() -> "S3Client":
    """Client construit sur la clé d'administration (purge manuelle uniquement).

    Lève SystemExit si la clé n'est pas fournie : sur le VPS, son absence est
    l'état normal — la sauvegarde quotidienne ne doit jamais savoir supprimer.
    """
    admin = get_backup_admin_settings()
    if admin is None:
        raise SystemExit(
            "Purge refusée : la clé d'administration des sauvegardes "
            "(KORA_BACKUP_ADMIN_S3_ACCESS_KEY_ID / KORA_BACKUP_ADMIN_S3_SECRET_ACCESS_KEY) "
            "n'est pas fournie. La rétention est administrée côté fournisseur ; cette clé "
            "distincte de la clé de sauvegarde ne doit jamais résider sur le VPS."
        )
    settings = get_backup_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        aws_access_key_id=admin.access_key_id,
        aws_secret_access_key=admin.secret_access_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=settings.timeout_seconds,
            retries={"max_attempts": 3, "mode": "standard"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
