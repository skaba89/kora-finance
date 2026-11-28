"""Annulation définitive d'un batch d'import non validé.

L'annulation est l'acte miroir de la confirmation, à la demande explicite
d'un utilisateur autorisé :
- un batch jamais confirmé (simple dépôt) disparaît : référence, rapport
  persisté et objet chiffré ; la capacité du dossier est libérée aussitôt ;
- un batch confirmé voit ses brouillons **encore présents et encore
  brouillons** supprimés dans la même transaction que sa référence — un
  brouillon déjà supprimé par son auteur a emporté son lien (CASCADE) et
  ne compte plus ; les lignes suivent leur écriture ;
- toute écriture du batch devenue validée interdit l'annulation (409) :
  une écriture validée ne se corrige que par contre-passation, jamais par
  destruction ; le refus est intégral, rien n'est entamé ;
- tout ou rien : brouillons, liens de traçabilité, objet chiffré et
  référence partent ensemble ; la reprise est immédiate — le même fichier
  peut être redéposé et repart sur un batch neuf ;
- traçable : un événement d'audit `import.cancelled` complète la chaîne
  ouverte par `import.confirmed`, avec les comptes de la destruction ;
- sérialisé : le verrou de ligne du batch rend l'annulation et la
  confirmation mutuellement exclusives, quel que soit l'ordre d'arrivée ;
- idempotent par disparition : répéter l'annulation répond 404, comme
  toute opération sur un batch purge.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.accounting.import_storage import _check_rate
from kora.attachments import service as attachments
from kora.audit.service import record_event
from kora.core.errors import ConflictError, ForbiddenError, NotFoundError
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import Company, User
from kora.models.imports import ImportBatch, ImportBatchEntry
from kora.models.ledger import EntryStatus, JournalEntry, JournalLine
from kora.storage import objects
from kora.tenancy.access import resolve_role
from kora.tenancy.permissions import Permission, permissions_for


@dataclass(frozen=True)
class ImportCancellation:
    """Résultat borné d'une annulation : des comptes, jamais le contenu."""

    batch_id: uuid.UUID
    cancelled_at: datetime
    entries_removed: int
    lines_removed: int


def _authorize(session: Session, user: User, company_id: uuid.UUID) -> None:
    """RLS + rôle : l'annulation exige le même droit d'écriture que la confirmation.

    Aucune exigence de devise : un batch devenu étranger au dossier (devise
    modifiée après dépôt) reste annulable — c'est précisément lui qu'il faut
    pouvoir retirer.
    """
    bind_tenant(session, company_id)
    role = resolve_role(session, user, company_id)
    if role is None:
        raise NotFoundError("Dossier introuvable.")
    if Permission.ENTRIES_WRITE not in permissions_for(role):
        raise ForbiddenError("Votre rôle ne permet pas cette action.")
    found = session.scalar(select(Company.id).where(Company.id == company_id))
    if found is None:
        raise NotFoundError("Dossier introuvable.")


def cancel_staged_import(
    user: User, company_id: uuid.UUID, batch_id: uuid.UUID, *, actor: Actor
) -> ImportCancellation:
    """Annule le batch : brouillons restants, liens, objet et référence en une
    transaction ; refuse intégralement si une écriture a été validée."""
    _check_rate(user.id, company_id, "cancel")
    purge_keys: list[str] = []
    cancelled_at = utcnow()
    with get_sessionmaker()() as session, session.begin():
        _authorize(session, user, company_id)
        batch = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == company_id, ImportBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None or batch.expires_at <= utcnow():
            raise NotFoundError("Import introuvable ou expiré.")
        confirmed_entries = batch.confirmed_entries
        removed = 0
        total_lines = 0
        if confirmed_entries is not None:
            entry_ids = list(
                session.scalars(
                    select(ImportBatchEntry.entry_id).where(
                        ImportBatchEntry.tenant_id == company_id,
                        ImportBatchEntry.batch_id == batch_id,
                    )
                )
            )
            for entry_id in entry_ids:
                entry = session.execute(
                    select(JournalEntry)
                    .where(JournalEntry.id == entry_id, JournalEntry.tenant_id == company_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if entry is None:
                    continue  # brouillon déjà supprimé par son auteur : le lien a suivi.
                if entry.status != EntryStatus.DRAFT:
                    raise ConflictError(
                        "Ce batch contient une écriture validée : il ne peut plus être "
                        "annulé. Corrigez-la par une contre-passation."
                    )
                total_lines += session.execute(
                    select(func.count())
                    .select_from(JournalLine)
                    .where(JournalLine.entry_id == entry_id)
                ).scalar_one()
                purge_keys.extend(attachments.detach_all(session, company_id, entry.id))
                session.delete(entry)
                removed += 1
        objects.delete(batch.storage_key)
        session.delete(batch)
        record_event(
            session,
            action="import.cancelled",
            entity_type="accounting_import_batch",
            entity_id=batch_id,
            payload={
                "brouillons": removed,
                "lignes": total_lines,
                "confirmes": confirmed_entries,
            },
            actor_user_id=actor.user_id,
            ip_address=actor.ctx.ip_address,
        )
    # Objets des pièces jointes des brouillons, une fois la transaction validée.
    attachments.purge(purge_keys)
    return ImportCancellation(
        batch_id=batch_id,
        cancelled_at=cancelled_at,
        entries_removed=removed,
        lines_removed=total_lines,
    )
