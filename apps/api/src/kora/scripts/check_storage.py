"""Vérifie le stockage S3 configuré (KORA_S3_*) avant une mise en production.

Écrit un objet de test chiffré, le relit, contrôle qu'il est bien chiffré, puis le
supprime (toutes versions). Signale aussi une configuration risquée : point d'accès
non https, clé d'accès qui voit d'autres buckets. Aucun secret n'est affiché.

Lancement : `python -m kora.scripts.check_storage` (code de sortie 0 = tout est bon).
"""

import os
import sys
import uuid
from collections.abc import Callable

from botocore.exceptions import BotoCoreError, ClientError

from kora.core.config import get_settings
from kora.core.errors import ServiceUnavailableError
from kora.storage import objects

_PREFIX = "verification-kora/"


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", "inconnu"))
    return type(exc).__name__


def _delete_all_versions(key: str) -> None:
    """Les services versionnés (Backblaze B2…) gardent l'objet sous un marqueur de
    suppression : l'objet de test est effacé version par version."""
    client = objects._client()
    bucket = get_settings().s3_bucket
    try:
        listed = client.list_object_versions(Bucket=bucket, Prefix=key)
    except ClientError:
        return  # service sans versions : la suppression simple suffit
    for item in [*listed.get("Versions", []), *listed.get("DeleteMarkers", [])]:
        if item.get("Key") == key and item.get("VersionId"):
            client.delete_object(Bucket=bucket, Key=key, VersionId=item["VersionId"])


def run(out: Callable[[str], None] = print) -> bool:
    settings = get_settings()
    out(f"Point d'accès : {settings.s3_endpoint_url} (région {settings.s3_region})")
    out(f"Bucket        : {settings.s3_bucket}")
    out(f"Clé d'accès   : {settings.s3_access_key_id}")
    warnings: list[str] = []
    if not settings.s3_endpoint_url.startswith("https://"):
        warnings.append("le point d'accès n'est pas en https:// (refusé en production)")

    client = objects._client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except (BotoCoreError, ClientError) as exc:
        out(f"ÉCHEC : bucket inaccessible ({_error_code(exc)}). Vérifiez le point d'accès, ")
        out("la région, le nom du bucket et les droits de la clé.")
        return False
    out("OK  bucket accessible")

    try:
        visible = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    except ClientError:
        visible = []  # clé restreinte sans droit de lister : c'est le cas souhaité
    others = [name for name in visible if name != settings.s3_bucket]
    if others:
        warnings.append(
            f"la clé voit {len(others)} autre(s) bucket(s) : utilisez une clé limitée "
            "à ce seul bucket (jamais la clé principale du compte)"
        )

    key = f"{_PREFIX}{uuid.uuid4()}"
    payload = os.urandom(64 * 1024)
    try:
        sealed = objects.seal(payload, key)
        objects.put(key, sealed)
        out("OK  écriture d'un objet chiffré")
        blob = objects.get(key)
        if payload[:64] in blob:
            out("ÉCHEC : l'objet relu n'est pas chiffré.")
            return False
        if objects.unseal(blob, sealed.wrapped_key, key) != payload:
            out("ÉCHEC : l'objet relu ne correspond pas à l'objet écrit.")
            return False
        out("OK  relecture et déchiffrement identiques")
    except (
        BotoCoreError,
        ClientError,
        ServiceUnavailableError,
        objects.CorruptedObjectError,
    ) as exc:
        out(f"ÉCHEC : écriture ou lecture impossible ({_error_code(exc.__cause__ or exc)}).")
        return False
    finally:
        try:
            objects.delete(key)
            _delete_all_versions(key)
        except (BotoCoreError, ClientError) as exc:
            warnings.append(f"objet de test {key} non supprimé ({_error_code(exc)})")

    try:
        client.head_object(Bucket=settings.s3_bucket, Key=key)
        warnings.append(f"l'objet de test {key} existe encore après suppression")
    except ClientError:
        out("OK  suppression")

    out("Stockage opérationnel." if not warnings else "Stockage opérationnel, à corriger :")
    for warning in warnings:
        out(f"ATTENTION : {warning}")
    return not warnings


def main() -> None:
    sys.exit(0 if run() else 1)


if __name__ == "__main__":
    main()
