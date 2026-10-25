"""Pièces justificatives : ajout, lecture, retrait.

Ordre des opérations à l'ajout : l'objet chiffré est d'abord écrit dans le stockage,
puis la pièce est enregistrée en base. Si l'enregistrement échoue, l'objet est retiré :
une pièce en base désigne toujours un objet existant. Au retrait, la base d'abord,
l'objet ensuite (en tâche de fond si le stockage ne répond pas).
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.config import get_settings
from kora.core.errors import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
)
from kora.models.attachments import Attachment, AttachmentType
from kora.models.ledger import EntryStatus, JournalEntry
from kora.storage import objects
from kora.worker import tasks
from kora.worker.enqueue import enqueue_best_effort

if TYPE_CHECKING:
    # Annotations seulement : le module des écritures importe celui-ci.
    from kora.accounting.entries import Actor

logger = logging.getLogger(__name__)

ACCEPTED_FORMATS = "PDF, JPEG, PNG ou WebP"
_FILENAME_MAX = 200


def detect_type(content: bytes) -> AttachmentType | None:
    """Type réel d'après la signature du fichier, jamais d'après l'extension ou
    l'en-tête Content-Type fournis par le client."""
    if content.startswith(b"%PDF-"):
        return AttachmentType.PDF
    if content.startswith(b"\xff\xd8\xff"):
        return AttachmentType.JPEG
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return AttachmentType.PNG
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return AttachmentType.WEBP
    return None


def clean_filename(raw: str) -> str:
    """Nom affiché et proposé au téléchargement : sans chemin ni caractère de contrôle."""
    name = unicodedata.normalize("NFC", raw).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip(" .")
    return name[:_FILENAME_MAX].strip() or "piece"


def too_large() -> PayloadTooLargeError:
    limit_mb = get_settings().attachment_max_bytes // (1024 * 1024)
    return PayloadTooLargeError(f"Fichier trop volumineux (maximum {limit_mb} Mo).")


def storage_key(company_id: uuid.UUID, attachment_id: uuid.UUID) -> str:
    return f"attachments/{company_id}/{attachment_id}"


@dataclass(frozen=True)
class Added:
    attachment: Attachment
    # False : le même fichier était déjà attaché (réessai d'un envoi), rien n'a changé.
    created: bool


def _entry(session: Session, actor: Actor, entry_id: uuid.UUID, *, lock: bool) -> JournalEntry:
    query = select(JournalEntry).where(
        JournalEntry.id == entry_id, JournalEntry.tenant_id == actor.company_id
    )
    entry = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if entry is None:
        raise NotFoundError("Écriture introuvable.")
    return entry


def _get(session: Session, company_id: uuid.UUID, attachment_id: uuid.UUID) -> Attachment:
    attachment = session.execute(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.tenant_id == company_id)
    ).scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("Pièce introuvable.")
    return attachment


def _audit(session: Session, actor: Actor, action: str, attachment: Attachment) -> None:
    record_event(
        session,
        action=action,
        entity_type="attachment",
        entity_id=attachment.id,
        payload={
            "entry_id": str(attachment.entry_id),
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "sha256": attachment.sha256,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )


def _existing(
    session: Session, actor: Actor, entry_id: uuid.UUID, digest: str
) -> Attachment | None:
    return session.execute(
        select(Attachment).where(
            Attachment.tenant_id == actor.company_id,
            Attachment.entry_id == entry_id,
            Attachment.sha256 == digest,
        )
    ).scalar_one_or_none()


def add(
    session: Session, actor: Actor, entry_id: uuid.UUID, filename: str, content: bytes
) -> Added:
    settings = get_settings()
    if not content:
        raise BusinessRuleError("Le fichier est vide.")
    if len(content) > settings.attachment_max_bytes:
        raise too_large()
    content_type = detect_type(content)
    if content_type is None:
        raise BusinessRuleError(f"Format non accepté : {ACCEPTED_FORMATS}.")

    # Verrou de l'écriture : sérialise les ajouts (plafond) et les retraits concurrents.
    _entry(session, actor, entry_id, lock=True)
    digest = hashlib.sha256(content).hexdigest()
    existing = _existing(session, actor, entry_id, digest)
    if existing is not None:
        session.expunge(existing)
        session.rollback()
        return Added(existing, created=False)
    count = session.execute(
        select(func.count()).where(
            Attachment.tenant_id == actor.company_id, Attachment.entry_id == entry_id
        )
    ).scalar_one()
    if count >= settings.attachments_per_entry:
        raise BusinessRuleError(
            f"Une écriture porte au plus {settings.attachments_per_entry} pièces."
        )

    attachment_id = uuid.uuid4()
    key = storage_key(actor.company_id, attachment_id)
    sealed = objects.seal(content, key)
    objects.put(key, sealed)
    attachment = Attachment(
        id=attachment_id,
        tenant_id=actor.company_id,
        entry_id=entry_id,
        filename=clean_filename(filename),
        content_type=content_type.value,
        size_bytes=len(content),
        sha256=digest,
        storage_key=key,
        wrapped_key=sealed.wrapped_key,
        uploaded_by_user_id=actor.user_id,
    )
    try:
        session.add(attachment)
        session.flush()
        _audit(session, actor, "attachment.added", attachment)
        session.commit()
    except BaseException:
        session.rollback()
        purge([key])
        raise
    return Added(attachment, created=True)


def list_for_entry(
    session: Session, company_id: uuid.UUID, entry_id: uuid.UUID
) -> list[Attachment]:
    return list(
        session.execute(
            select(Attachment)
            .where(Attachment.tenant_id == company_id, Attachment.entry_id == entry_id)
            .order_by(Attachment.created_at, Attachment.id)
        ).scalars()
    )


def read(
    session: Session, company_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[Attachment, bytes]:
    attachment = _get(session, company_id, attachment_id)
    # La transaction n'est pas gardée ouverte pendant le téléchargement depuis le stockage.
    session.expunge(attachment)
    session.rollback()
    blob = objects.get(attachment.storage_key)
    try:
        content = objects.unseal(blob, attachment.wrapped_key, attachment.storage_key)
    except objects.CorruptedObjectError:
        content = b""
    if not content or hashlib.sha256(content).hexdigest() != attachment.sha256:
        logger.error(
            "Pièce justificative altérée ou illisible",
            extra={"piece": str(attachment.id), "objet": attachment.storage_key},
        )
        raise ConflictError(
            "Cette pièce est illisible : son contenu ne correspond plus à l'original. "
            "Signalez-le au support."
        )
    return attachment, content


def remove(session: Session, actor: Actor, attachment_id: uuid.UUID) -> None:
    attachment = _get(session, actor.company_id, attachment_id)
    entry = _entry(session, actor, attachment.entry_id, lock=True)
    if entry.status != EntryStatus.DRAFT:
        raise ConflictError(
            "La pièce d'une écriture validée est conservée : elle ne peut pas être retirée."
        )
    _audit(session, actor, "attachment.removed", attachment)
    session.execute(delete(Attachment).where(Attachment.id == attachment.id))
    session.commit()
    purge([attachment.storage_key])


def detach_all(session: Session, company_id: uuid.UUID, entry_id: uuid.UUID) -> list[str]:
    """Pour la suppression d'un brouillon (dans la même transaction) : retire les pièces
    et renvoie les objets à purger une fois la transaction validée."""
    keys = session.execute(
        delete(Attachment)
        .where(Attachment.tenant_id == company_id, Attachment.entry_id == entry_id)
        .returning(Attachment.storage_key)
    ).scalars()
    return list(keys)


def purge(keys: Sequence[str]) -> None:
    """Supprime des objets du stockage. Un échec n'annule rien : la suppression est
    confiée au worker, qui réessaie."""
    for key in keys:
        try:
            objects.delete(key)
        except (BotoCoreError, ClientError):
            logger.warning("Suppression d'objet reportée", extra={"objet": key})
            if not enqueue_best_effort(tasks.delete_stored_object, key):
                # Objet chiffré orphelin, sans référence en base : à purger à la main.
                logger.error("Objet orphelin dans le stockage", extra={"objet": key})
