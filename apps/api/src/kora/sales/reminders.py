"""Relances de factures échues (Phase 4D).

Règles portées par le service (et la base quand possible) :
- une relance vise une facture ÉMISE, ÉCHUE (échéance passée à la date du
  rappel) et non soldée (solde restant dû strictement positif, calculé comme en
  4C : TTC - affectations - avoirs partiels émis) ; une facture sans échéance
  n'est jamais « échue » (même convention que la balance âgée) ;
- le niveau (1re, 2e, 3e relance…) est compté par le service sous verrou FOR
  UPDATE de la facture — jamais saisi par l'appelant ; l'unicité
  (facture, jour du rappel) en base empêche tout doublon, y compris en course
  concurrente (le contraignant est traduit en 409) ;
- la relance est immuable : un email envoyé ne se « désend » pas — aucune
  modification ni suppression ; la correction d'une adresse erronée passe par
  la fiche du tier, le renvoi (journalisé) par la route dédiée ;
- l'envoi réel part dans le worker (jamais pendant la requête HTTP) : la panne
  du fournisseur d'email n'annule ni ne bloque la relance — si la file est
  injoignable, la relance reste enregistrée et `email_queued` est False, le
  renvoi est possible depuis l'historique ;
- aucune écriture comptable n'est générée ici (garde-fou testé, comme en 4A,
  4B et 4C) : la relance est un acte commercial documenté, pas un fait
  financier.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.email.sender import OutgoingEmail
from kora.email.templates import render
from kora.models.common import utcnow
from kora.models.identity import Company
from kora.models.partners import Partner
from kora.models.sales import (
    DocKind,
    DocStatus,
    ReminderChannel,
    SalesDocument,
    SalesReminder,
)
from kora.sales import payments


@dataclass(frozen=True)
class ReminderData:
    """Relance demandée : la facture visée, la date du rappel et un message
    personnalisé facultatif. Le niveau n'est jamais fourni : il est compté."""

    document_id: uuid.UUID
    reminded_on: date
    note: str | None = None


@dataclass(frozen=True)
class OverdueInvoice:
    """Une facture échue candidate à la relance : solde restant dû, ancienneté
    du retard et historique de relances déjà envoyées."""

    document: SalesDocument
    partner_name: str
    partner_email: str | None
    outstanding_ttc: int
    days_late: int
    reminders_count: int
    next_level: int


def reminders_count_for_documents(
    session: Session, company_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Nombre de relances déjà envoyées par facture (une requête GROUP BY)."""
    if not document_ids:
        return {}
    rows = session.execute(
        select(
            SalesReminder.document_id,
            func.count().label("total"),
        )
        .where(
            SalesReminder.tenant_id == company_id,
            SalesReminder.document_id.in_(document_ids),
        )
        .group_by(SalesReminder.document_id)
    )
    return {row.document_id: int(row.total) for row in rows}


def overdue_invoices(session: Session, company_id: uuid.UUID, as_of: date) -> list[OverdueInvoice]:
    """Factures émises échues et non soldées au {as_of} : candidates à la
    relance, triées du retard le plus ancien au plus récent (puis numéro). Le
    destinataire et son email viennent de la fiche du tier."""
    invoices = list(
        session.execute(
            select(SalesDocument).where(
                SalesDocument.tenant_id == company_id,
                SalesDocument.doc_kind == DocKind.INVOICE.value,
                SalesDocument.status == DocStatus.ISSUED.value,
                SalesDocument.due_on.is_not(None),
                SalesDocument.due_on < as_of,
            )
        ).scalars()
    )
    if not invoices:
        return []
    lettres = payments.outstanding_for_documents(session, company_id, [i.id for i in invoices])
    compteurs = reminders_count_for_documents(session, company_id, [i.id for i in invoices])
    partners = {
        row.id: row
        for row in session.execute(
            select(Partner).where(
                Partner.tenant_id == company_id,
                Partner.id.in_({i.partner_id for i in invoices}),
            )
        ).scalars()
    }
    candidates: list[OverdueInvoice] = []
    for invoice in invoices:
        solde = invoice.total_ttc - lettres.get(invoice.id, 0)
        if solde <= 0:
            continue
        partner = partners.get(invoice.partner_id)
        nombre = compteurs.get(invoice.id, 0)
        candidates.append(
            OverdueInvoice(
                document=invoice,
                partner_name=partner.name if partner else "",
                partner_email=partner.email if partner else None,
                outstanding_ttc=solde,
                days_late=(as_of - (invoice.due_on or as_of)).days,
                reminders_count=nombre,
                next_level=nombre + 1,
            )
        )
    return sorted(
        candidates,
        key=lambda c: (-(c.days_late), c.document.number or 0),
    )


def get_reminder(session: Session, company_id: uuid.UUID, reminder_id: uuid.UUID) -> SalesReminder:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    reminder = session.execute(
        select(SalesReminder).where(
            SalesReminder.id == reminder_id, SalesReminder.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if reminder is None:
        raise NotFoundError("Relance introuvable dans ce dossier.")
    return reminder


def _charge_facture(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> SalesDocument:
    """Verrou de ligne (FOR UPDATE) de la facture visée : la sérialisation des
    niveaux — deux relances concurrentes ne peuvent pas compter le même niveau —
    et des contrôles (une facture absente du dossier est un 404 — la RLS ne la
    laisse pas voir)."""
    invoice = session.execute(
        select(SalesDocument)
        .where(
            SalesDocument.tenant_id == company_id,
            SalesDocument.id == document_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Facture introuvable dans ce dossier.")
    return invoice


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def create_reminder(session: Session, actor: Actor, data: ReminderData) -> SalesReminder:
    """Enregistre une relance (niveau compté sous verrou, unicité quotidienne)
    et journalise l'acte. L'envoi email est programmé PAR LA ROUTE après le
    commit : une panne de la file n'annule pas l'enregistrement (voir
    `enqueue_best_effort` et la route POST)."""
    if data.reminded_on > utcnow().date():
        raise BusinessRuleError("La date d'une relance ne peut pas être dans le futur.")
    invoice = _charge_facture(session, actor.company_id, data.document_id)
    if invoice.doc_kind != DocKind.INVOICE.value:
        raise BusinessRuleError("Une relance ne vise qu'une facture (pas un devis ni un avoir).")
    if invoice.status == DocStatus.DRAFT.value:
        raise ConflictError("Une facture brouillon n'a pas encore été émise au client.")
    if invoice.status != DocStatus.ISSUED.value:
        raise ConflictError("Une facture annulée ne reçoit pas de relance.")
    if invoice.due_on is None or invoice.due_on >= data.reminded_on:
        raise BusinessRuleError(
            "La facture n'est pas encore échue à la date du rappel : pas de relance."
        )
    lettres = payments.outstanding_for_documents(session, actor.company_id, [invoice.id])
    solde = invoice.total_ttc - lettres.get(invoice.id, 0)
    if solde <= 0:
        raise BusinessRuleError(
            f"La facture numérotée {invoice.number} est soldée : pas de relance."
        )
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == invoice.partner_id
        )
    ).scalar_one()
    if not partner.email or not partner.email.strip():
        raise BusinessRuleError(
            "Le tier n'a pas d'adresse email : complétez sa fiche avant de relancer."
        )
    niveau = (
        reminders_count_for_documents(session, actor.company_id, [invoice.id]).get(invoice.id, 0)
        + 1
    )
    reminder = SalesReminder(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        document_id=invoice.id,
        partner_id=invoice.partner_id,
        level=niveau,
        reminded_on=data.reminded_on,
        channel=ReminderChannel.EMAIL.value,
        email_to=partner.email.strip(),
        note=_clean(data.note),
        created_by_user_id=actor.user_id,
    )
    # Doublon du jour : contrôlé APRÈS l'acquisition du verrou de la facture —
    # deux relances concurrentes se sérialisent sur le verrou FOR UPDATE, la
    # seconde voit la relance commise par la première et refuse avant tout
    # INSERT (409). Le contraignant d'unicité (dossier, facture, jour) reste le
    # juge de paix : sa violation est traduite en 409 après rollback complet —
    # la relance et son audit partagent la même transaction.
    existante = session.execute(
        select(SalesReminder.id).where(
            SalesReminder.tenant_id == actor.company_id,
            SalesReminder.document_id == invoice.id,
            SalesReminder.reminded_on == data.reminded_on,
        )
    ).scalar_one_or_none()
    if existante is not None:
        raise ConflictError(
            f"Une relance de la facture numérotée {invoice.number} a déjà été "
            f"enregistrée le {data.reminded_on.isoformat()}."
        )
    session.add(reminder)
    record_event(
        session,
        action="sales_reminder.created",
        entity_type="sales_reminder",
        entity_id=reminder.id,
        payload={
            "facture": invoice.number,
            "niveau": niveau,
            "canal": ReminderChannel.EMAIL.value,
            "jours_retard": (data.reminded_on - invoice.due_on).days,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"Une relance de la facture numérotée {invoice.number} a déjà été "
            f"enregistrée le {data.reminded_on.isoformat()}."
        ) from exc
    return reminder


def resend_reminder(session: Session, actor: Actor, reminder_id: uuid.UUID) -> None:
    """Re-programme l'envoi email d'une relance déjà enregistrée (après une file
    injoignable, par exemple). L'action est journalisée ; la relance elle-même
    reste inchangée (immuable)."""
    reminder = get_reminder(session, actor.company_id, reminder_id)
    record_event(
        session,
        action="sales_reminder.resent",
        entity_type="sales_reminder",
        entity_id=reminder.id,
        payload={"facture_canal": reminder.channel, "niveau": reminder.level},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()


def list_reminders(
    session: Session,
    company_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    partner_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SalesReminder], int]:
    """Liste paginée et filtrée des relances ; renvoie (items, total)."""
    query = select(SalesReminder).where(SalesReminder.tenant_id == company_id)
    count = (
        select(func.count()).select_from(SalesReminder).where(SalesReminder.tenant_id == company_id)
    )
    if document_id is not None:
        query = query.where(SalesReminder.document_id == document_id)
        count = count.where(SalesReminder.document_id == document_id)
    if partner_id is not None:
        query = query.where(SalesReminder.partner_id == partner_id)
        count = count.where(SalesReminder.partner_id == partner_id)
    if date_from is not None:
        query = query.where(SalesReminder.reminded_on >= date_from)
        count = count.where(SalesReminder.reminded_on >= date_from)
    if date_to is not None:
        query = query.where(SalesReminder.reminded_on <= date_to)
        count = count.where(SalesReminder.reminded_on <= date_to)
    total = session.execute(count).scalar_one()
    items = list(
        session.execute(
            query.order_by(SalesReminder.reminded_on.desc(), SalesReminder.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return items, total


def prepare_email(session: Session, reminder_id: uuid.UUID) -> OutgoingEmail:
    """Compose l'email de relance depuis l'état persisté (chargé par le worker,
    tenant explicitement lié à la session pour la RLS). La langue du rappel est
    le français : langue commerciale des clients visés (PME guinéennes) — un
    gabarit par locale du tier est une évolution. LookupError si la relance a
    disparu (dossier supprimé) : le worker abandonne."""
    reminder = session.execute(
        select(SalesReminder).where(SalesReminder.id == reminder_id)
    ).scalar_one_or_none()
    if reminder is None:
        raise LookupError(f"relance {reminder_id} introuvable : envoi abandonné")
    invoice = session.get_one(SalesDocument, reminder.document_id)
    partner = session.get_one(Partner, reminder.partner_id)
    company = session.get_one(Company, reminder.tenant_id)
    solde = invoice.total_ttc - payments.outstanding_for_documents(
        session, reminder.tenant_id, [invoice.id]
    ).get(invoice.id, 0)
    jours = (reminder.reminded_on - (invoice.due_on or reminder.reminded_on)).days
    montant = f"{solde:,}".replace(",", " ")
    due = invoice.due_on.isoformat() if invoice.due_on else ""
    message = (
        f"\n\nMessage de « {company.legal_name or company.trade_name} » :\n{reminder.note}"
        if reminder.note
        else ""
    )
    return render(
        "invoice_reminder",
        "fr",
        to=reminder.email_to,
        partner_name=partner.name,
        company=company.legal_name or company.trade_name or "",
        number=_numero_affichage(invoice),
        days=str(jours),
        due_on=due,
        amount=montant,
        currency=invoice.currency,
        level=str(reminder.level),
        note_extra=message,
    )


def _numero_affichage(invoice: SalesDocument) -> str:
    """Numéro d'affichage d'une facture : FAC-année-00042 (même convention que
    le front et le PDF)."""
    annee = invoice.issued_on.year if invoice.issued_on else ""
    return f"FAC-{annee}-{invoice.number:05d}" if invoice.number is not None else "FAC"
