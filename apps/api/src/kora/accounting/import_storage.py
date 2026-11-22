"""Staging chiffré des fichiers d'import, sans création d'écritures comptables."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from cryptography.fernet import InvalidToken
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.core import quota
from kora.core.errors import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    TooManyRequestsError,
)
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import Company, User
from kora.models.imports import ImportBatch
from kora.storage import objects
from kora.tenancy.access import resolve_role
from kora.tenancy.permissions import Permission, permissions_for

MAX_STAGED_FILES = 10
MAX_STAGED_BYTES = 128 * 1024 * 1024


def _check_rate(user_id: uuid.UUID, company_id: uuid.UUID, operation: str) -> None:
    """Budget partagé entre formats ; une panne Redis bloque l'opération."""
    try:
        for scope, subject, limit in (("user", user_id, 20), ("company", company_id, 60)):
            if not quota.allowed(
                f"import-{operation}-{scope}", str(subject), limit=limit, window_seconds=quota.HOUR
            ):
                raise TooManyRequestsError(
                    "Limite horaire des imports atteinte.",
                    headers={"Retry-After": quota.retry_after(quota.HOUR)},
                )
    except RedisError as exc:
        raise ServiceUnavailableError("Le service d'import est indisponible.") from exc


def _check_capacity(session: Session, company_id: uuid.UUID, size: int) -> None:
    # Sous le verrou du dossier : inclut les références expirées non encore purgées.
    total_bytes = func.coalesce(func.sum(ImportBatch.size_bytes), 0)
    tenant_filter = ImportBatch.tenant_id == company_id
    query = select(func.count(ImportBatch.id), total_bytes).where(tenant_filter)
    count, total = session.execute(query).one()
    if count >= MAX_STAGED_FILES or total + size > MAX_STAGED_BYTES:
        raise ConflictError("Capacité des imports atteinte. Attendez la purge des fichiers.")


@dataclass(frozen=True)
class StagedImport:
    id: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True)
class StagedContent:
    content: bytes
    file_format: Literal["csv", "fec", "xlsx"]
    currency: str
    fec_delimiter: Literal["\t", "|"]


def _authorize(session: Session, user: User, company_id: uuid.UUID, *, lock: bool) -> str:
    bind_tenant(session, company_id)
    role = resolve_role(session, user, company_id)
    if role is None:
        raise NotFoundError("Dossier introuvable.")
    if Permission.ENTRIES_WRITE not in permissions_for(role):
        raise ForbiddenError("Votre rôle ne permet pas cette action.")
    query = select(Company.currency).where(Company.id == company_id)
    currency = session.scalar(query.with_for_update() if lock else query)
    if currency is None:
        raise NotFoundError("Dossier introuvable.")
    return currency


def stage_import(
    user: User,
    company_id: uuid.UUID,
    content: bytes,
    *,
    file_format: Literal["csv", "fec", "xlsx"],
    source_currency: str,
    fec_delimiter: Literal["\t", "|"] = "|",
) -> StagedImport:
    """Réserve puis dépose un objet unique ; un rejeu ne prolonge pas sa durée de vie.

    En cas d'échec ambigu du stockage ou du commit, un objet orphelin peut
    subsister : la future purge réconciliera les objets et les références.
    Ne jamais supprimer ici un objet dont le commit pourrait avoir réussi.
    """
    with get_sessionmaker()() as session, session.begin():
        currency = _authorize(session, user, company_id, lock=True)
        if currency != "GNF" or source_currency != currency:
            raise BusinessRuleError("La devise source doit correspondre au dossier en GNF.")
        if file_format not in ("csv", "fec", "xlsx") or fec_delimiter not in ("\t", "|"):
            raise BusinessRuleError("Format d'import non pris en charge.")
        if not content:
            raise BusinessRuleError("Le fichier est vide.")
        if len(content) > (16 if file_format == "xlsx" else 32) * 1024 * 1024:
            raise PayloadTooLargeError("Le fichier dépasse la taille maximale autorisée.")
        _check_rate(user.id, company_id, "stage")
        delimiter = "NONE"
        if file_format == "fec":
            delimiter = "TAB" if fec_delimiter == "\t" else "PIPE"
        digest = hashlib.sha256(content).hexdigest()
        existing = session.scalar(
            select(ImportBatch).where(
                ImportBatch.tenant_id == company_id,
                ImportBatch.sha256 == digest,
                ImportBatch.format == file_format,
                ImportBatch.currency == currency,
                ImportBatch.delimiter == delimiter,
            )
        )
        if existing is not None:
            if existing.expires_at <= utcnow():
                raise ConflictError("Cet import a expiré et doit être purgé avant un nouvel envoi.")
            return StagedImport(existing.id, existing.expires_at)
        _check_capacity(session, company_id, len(content))
        batch_id = uuid.uuid4()
        key = f"imports/{company_id}/{batch_id}"
        sealed = objects.seal(content, key)
        now = utcnow()
        batch = ImportBatch(
            id=batch_id,
            tenant_id=company_id,
            uploaded_by_user_id=user.id,
            format=file_format,
            currency=currency,
            delimiter=delimiter,
            size_bytes=len(content),
            sha256=digest,
            storage_key=key,
            wrapped_key=sealed.wrapped_key,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        session.add(batch)
        session.flush()
        objects.put(key, sealed)
        return StagedImport(batch.id, batch.expires_at)


def read_staged_import(user: User, company_id: uuid.UUID, batch_id: uuid.UUID) -> bytes:
    return load_staged_content(user, company_id, batch_id).content


def load_staged_content(user: User, company_id: uuid.UUID, batch_id: uuid.UUID) -> StagedContent:
    """Réautorise chaque lecture ; n'expose jamais de clé ni de lien de stockage."""
    with get_sessionmaker()() as session, session.begin():
        _authorize(session, user, company_id, lock=False)
        _check_rate(user.id, company_id, "read")
        batch = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == company_id, ImportBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None or batch.expires_at <= utcnow():
            raise NotFoundError("Import introuvable ou expiré.")
        try:
            # AES-GCM : nonce de 12 octets et tag de 16 octets.
            blob = objects.get(batch.storage_key, max_bytes=batch.size_bytes + 28)
            content = objects.unseal(blob, batch.wrapped_key, batch.storage_key)
        except (objects.CorruptedObjectError, InvalidToken) as exc:
            raise ServiceUnavailableError("Le fichier d'import est illisible.") from exc
        if len(content) != batch.size_bytes or hashlib.sha256(content).hexdigest() != batch.sha256:
            raise ServiceUnavailableError("Le fichier d'import est illisible.")
        if batch.format not in ("csv", "fec", "xlsx"):
            raise ServiceUnavailableError("Le format enregistré est inconnu.")
        file_format = cast(Literal["csv", "fec", "xlsx"], batch.format)
        return StagedContent(
            content, file_format, batch.currency, "\t" if batch.delimiter == "TAB" else "|"
        )
