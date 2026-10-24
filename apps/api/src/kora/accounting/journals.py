"""Journaux comptables d'un dossier."""

import uuid
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth.service import RequestContext
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.ledger import Journal, JournalKind

# Journaux créés avec chaque dossier. À valider par un expert-comptable guinéen
# (codes et libellés usuels). Toute modification doit être reportée dans une
# migration pour les dossiers existants (voir 0005).
DEFAULT_JOURNALS: tuple[tuple[str, str, JournalKind], ...] = (
    ("AC", "Achats", JournalKind.ACHATS),
    ("VT", "Ventes", JournalKind.VENTES),
    ("BQ", "Banque", JournalKind.TRESORERIE),
    ("CA", "Caisse", JournalKind.TRESORERIE),
    ("MM", "Mobile Money", JournalKind.TRESORERIE),
    ("OD", "Opérations diverses", JournalKind.OPERATIONS_DIVERSES),
    ("AN", "À-nouveaux", JournalKind.A_NOUVEAUX),
)


def create_default_journals(session: Session, company_id: uuid.UUID) -> None:
    session.execute(
        insert(Journal),
        [
            {"id": uuid.uuid4(), "tenant_id": company_id, "code": c, "label": lbl, "kind": k}
            for c, lbl, k in DEFAULT_JOURNALS
        ],
    )


def list_journals(session: Session, company_id: uuid.UUID) -> list[Journal]:
    return list(
        session.execute(
            select(Journal).where(Journal.tenant_id == company_id).order_by(Journal.code)
        ).scalars()
    )


def get_journal(session: Session, company_id: uuid.UUID, journal_id: uuid.UUID) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.id == journal_id, Journal.tenant_id == company_id)
    ).scalar_one_or_none()
    if journal is None:
        raise NotFoundError("Journal introuvable.")
    return journal


def _audit(
    session: Session,
    journal: Journal,
    *,
    action: str,
    payload: dict[str, Any],
    actor: uuid.UUID,
    ctx: RequestContext,
) -> None:
    record_event(
        session,
        action=action,
        entity_type="journal",
        entity_id=journal.id,
        payload=payload,
        actor_user_id=actor,
        ip_address=ctx.ip_address,
    )


def create_journal(
    session: Session,
    company_id: uuid.UUID,
    *,
    code: str,
    label: str,
    kind: JournalKind,
    actor: uuid.UUID,
    ctx: RequestContext,
) -> Journal:
    journal = Journal(tenant_id=company_id, code=code.upper(), label=label.strip(), kind=kind)
    session.add(journal)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"Le code de journal {journal.code} existe déjà.") from exc
    _audit(
        session,
        journal,
        action="journal.created",
        payload={"code": journal.code, "libelle": journal.label, "type": kind.value},
        actor=actor,
        ctx=ctx,
    )
    session.commit()
    return journal


def update_journal(
    session: Session,
    company_id: uuid.UUID,
    journal_id: uuid.UUID,
    *,
    label: str | None,
    is_active: bool | None,
    actor: uuid.UUID,
    ctx: RequestContext,
) -> Journal:
    """Le code et le type ne changent pas : ils identifient les écritures déjà numérotées."""
    journal = get_journal(session, company_id, journal_id)
    changes: dict[str, Any] = {}
    if label is not None and label.strip() != journal.label:
        if not label.strip():
            raise BusinessRuleError("Le libellé est obligatoire.")
        changes["libelle"] = {"avant": journal.label, "apres": label.strip()}
        journal.label = label.strip()
    if is_active is not None and is_active != journal.is_active:
        changes["actif"] = {"avant": journal.is_active, "apres": is_active}
        journal.is_active = is_active
    if changes:
        _audit(session, journal, action="journal.updated", payload=changes, actor=actor, ctx=ctx)
    session.commit()
    return journal
