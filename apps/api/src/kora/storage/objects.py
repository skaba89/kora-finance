"""Stockage chiffré des fichiers dans un service compatible S3.

Chaque objet est chiffré par l'application avant l'envoi (AES-256-GCM, clé aléatoire
propre à l'objet) : le fournisseur de stockage ne voit jamais le contenu. La clé de
l'objet est elle-même chiffrée par les clés maîtres `KORA_ENCRYPTION_KEYS` (Fernet,
rotation possible) et conservée en base, à côté de la référence de l'objet.
Le nom de l'objet sert de donnée authentifiée : un objet déplacé sous un autre nom
ne se déchiffre pas.
"""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kora.core import crypto
from kora.core.config import get_settings
from kora.core.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12
_UNAVAILABLE = "Le stockage des pièces est momentanément indisponible. Réessayez plus tard."


class CorruptedObjectError(Exception):
    """Objet illisible : altéré, tronqué ou associé à une autre clé."""


@dataclass(frozen=True)
class SealedObject:
    blob: bytes
    wrapped_key: bytes


def seal(plaintext: bytes, object_key: str) -> SealedObject:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, object_key.encode())
    return SealedObject(nonce + ciphertext, crypto.encrypt_bytes(data_key))


def unseal(blob: bytes, wrapped_key: bytes, object_key: str) -> bytes:
    try:
        data_key = crypto.decrypt_bytes(wrapped_key)
        return AESGCM(data_key).decrypt(
            blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], object_key.encode()
        )
    except (InvalidTag, ValueError) as exc:
        raise CorruptedObjectError(object_key) from exc


@lru_cache
def _client() -> "S3Client":
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=Config(
            # Adressage par chemin : compatible avec tous les fournisseurs S3.
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=settings.s3_timeout_seconds,
            retries={"max_attempts": 3, "mode": "standard"},
            # Sommes de contrôle étendues seulement si le service les exige (compatibilité).
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def put(object_key: str, sealed: SealedObject) -> None:
    try:
        _client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=object_key,
            Body=sealed.blob,
            ContentType="application/octet-stream",
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Écriture impossible dans le stockage", extra={"objet": object_key})
        raise ServiceUnavailableError(_UNAVAILABLE) from exc


def get(object_key: str) -> bytes:
    try:
        response = _client().get_object(Bucket=get_settings().s3_bucket, Key=object_key)
        body: bytes = response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Lecture impossible dans le stockage", extra={"objet": object_key})
        raise ServiceUnavailableError(_UNAVAILABLE) from exc
    return body


def delete(object_key: str) -> None:
    """Suppression idempotente (un objet absent n'est pas une erreur, comme en S3).
    Lève les erreurs du service : l'appelant décide de réessayer."""
    _client().delete_object(Bucket=get_settings().s3_bucket, Key=object_key)
