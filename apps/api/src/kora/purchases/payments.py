"""Décaissements fournisseurs et lettrage commercial des achats (Phase 4F).

Règles portées par le service (et la base quand possible) — miroir exact du
module ventes (Phase 4C) :
- un décaissement sort de l'argent : montant strictement positif, égal à la somme
  de ses affectations (le service le recalcule — jamais saisi par l'appelant) ;
- une affectation vise une facture fournisseur émise du même tier et de la même
  devise ; le montant ne dépasse jamais le solde restant dû (TTC - affectations -
  avoirs partiels émis), contrôlé sous verrou FOR UPDATE de la facture : deux
  règlements concurrents ne peuvent pas excéder le TTC ensemble ;
- la date de décaissement tombe dans un exercice ouvert (même règle que les
  documents d'achat) ;
- le règlement est immuable après création : une erreur se corrige en le
  supprimant (journalisé) puis en le re-saisissant ; supprimer un règlement
  libère le solde des factures qu'il lettrait ;
- une facture qui porte des décaissements ne peut plus être annulée (ni sans
  avoir, ni par avoir annulateur) tant que les décaissements n'ont pas été
  supprimés : l'annulation d'une facture payée exigerait de « détruire » de
  l'argent versé ;
- le solde restant dû se calcule en lecture (aucun statut dérivé stocké) :
  TTC - affectations - avoirs partiels émis ;
- l'échéancier fournisseurs (`payables_aging`) répartit les dettes d'achat
  non soldées par ancienneté de retard — la balance âgée des dettes ;
- aucune écriture comptable n'est générée ici : la comptabilisation est un acte
  explicite du comptable (permission `entries:post`), garde-fou testé comme en
  4A, 4B, 4C et 4D.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor, _fiscal_year_for, reversal_id_of
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.identity import Company
from kora.models.purchases import (
    PurchaseDocKind,
    PurchaseDocStatus,
    PurchaseDocument,
    PurchasePayment,
    PurchasePaymentAllocation,
)
from kora.models.sales import PaymentMethod

# Statut de paiement dérivé du solde, calculé en lecture (jamais stocké).
PaymentStatus = Literal["none", "partial", "paid"]
PAYMENT_NONE: PaymentStatus = "none"
PAYMENT_PARTIAL: PaymentStatus = "partial"
PAYMENT_PAID: PaymentStatus = "paid"


@dataclass(frozen=True)
class AllocationData:
    """Affectation saisie : facture visée et montant en unités mineures."""

    document_id: uuid.UUID
    amount: int


@dataclass(frozen=True)
class PaymentData:
    """Décaissement saisi : la date de paiement, le mode et les affectations.
    Le montant total n'est jamais saisi : c'est la somme des affectations."""

    paid_on: date
    method: str
    allocations: tuple[AllocationData, ...]
    reference: str | None = None
    notes: str | None = None


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def outstanding_for_documents(
    session: Session, company_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Sommes lettrées par facture : affectations de décaissements et avoirs
    partiels émis. Le solde restant dû = TTC - ces deux sommes (le calcul se
    fait en lecture : aucun statut dérivé stocké, aucune dérive possible)."""
    if not document_ids:
        return {}
    paid: dict[uuid.UUID, int] = {
        row.document_id: int(row.total or 0)
        for row in session.execute(
            select(
                PurchasePaymentAllocation.document_id,
                func.sum(PurchasePaymentAllocation.amount).label("total"),
            )
            .where(
                PurchasePaymentAllocation.tenant_id == company_id,
                PurchasePaymentAllocation.document_id.in_(document_ids),
            )
            .group_by(PurchasePaymentAllocation.document_id)
        )
    }
    credited: dict[uuid.UUID, int] = {
        row.origin_document_id: int(row.total or 0)
        for row in session.execute(
            select(
                PurchaseDocument.origin_document_id,
                func.sum(PurchaseDocument.total_ttc).label("total"),
            )
            .where(
                PurchaseDocument.tenant_id == company_id,
                PurchaseDocument.doc_kind == PurchaseDocKind.SUPPLIER_CREDIT_NOTE.value,
                PurchaseDocument.status == PurchaseDocStatus.ISSUED.value,
                PurchaseDocument.origin_document_id.in_(document_ids),
            )
            .group_by(PurchaseDocument.origin_document_id)
        )
    }
    return {doc_id: paid.get(doc_id, 0) + credited.get(doc_id, 0) for doc_id in document_ids}


def payment_status_for(outstanding: int, total_ttc: int) -> PaymentStatus:
    """Statut de paiement dérivé du solde : aucun (rien lettré), partiel, payé
    (solde couvert — y compris excédentaire si un avoir dépasse le TTC)."""
    if total_ttc <= 0 or outstanding <= 0:
        return PAYMENT_PAID
    if outstanding >= total_ttc:
        return PAYMENT_NONE
    return PAYMENT_PARTIAL


def get_payment(
    session: Session, company_id: uuid.UUID, payment_id: uuid.UUID
) -> tuple[PurchasePayment, list[PurchasePaymentAllocation]]:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    payment = session.execute(
        select(PurchasePayment).where(
            PurchasePayment.id == payment_id, PurchasePayment.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    allocations = list(
        session.execute(
            select(PurchasePaymentAllocation)
            .where(PurchasePaymentAllocation.payment_id == payment.id)
            .order_by(PurchasePaymentAllocation.document_id)
        ).scalars()
    )
    return payment, allocations


def _lock_invoices(
    session: Session, company_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> list[PurchaseDocument]:
    """Verrous de ligne des factures visées, dans un ordre déterministe (tri par
    identifiant) : deux règlements concurrents se sérialisent sans interblocage.
    Une facture absente du dossier est un 404 — la RLS ne la laisse pas voir."""
    ordered = sorted(set(document_ids))
    rows = list(
        session.execute(
            select(PurchaseDocument)
            .where(
                PurchaseDocument.tenant_id == company_id,
                PurchaseDocument.id.in_(ordered),
            )
            .with_for_update()
        ).scalars()
    )
    found = {row.id for row in rows}
    missing = [doc_id for doc_id in ordered if doc_id not in found]
    if missing:
        raise NotFoundError("Facture introuvable dans ce dossier.")
    return sorted(rows, key=lambda row: row.id)


def _controlle_factures(
    session: Session,
    actor: Actor,
    invoices: list[PurchaseDocument],
    allocations: tuple[AllocationData, ...],
) -> None:
    """Contrôles métier des factures visées et de leurs soldes, sous verrou :
    type et statut, tier unique, devise du dossier, unicité d'affectation,
    montant ≤ solde restant dû (affectations + avoirs partiels déjà comptés)."""
    par_facture = {row.document_id: row.amount for row in allocations}
    if len(par_facture) != len(allocations):
        raise BusinessRuleError("Un règlement ne s'affecte qu'une fois à une même facture.")
    partners = {invoice.partner_id for invoice in invoices}
    if len(partners) != 1:
        raise BusinessRuleError("Un règlement s'affecte aux factures d'un seul tier.")
    company = session.get_one(Company, actor.company_id)
    currencies = {invoice.currency for invoice in invoices}
    if currencies != {company.currency}:
        raise BusinessRuleError("Un règlement s'affecte à des factures de la devise du dossier.")
    lettres = outstanding_for_documents(
        session, actor.company_id, [invoice.id for invoice in invoices]
    )
    for invoice in invoices:
        if invoice.doc_kind != PurchaseDocKind.SUPPLIER_INVOICE.value:
            raise BusinessRuleError(
                "Un décaissement ne s'affecte qu'à une facture fournisseur (pas un avoir)."
            )
        if invoice.status != PurchaseDocStatus.ISSUED.value:
            raise ConflictError("Seule une facture émise peut recevoir un règlement.")
        montant = par_facture[invoice.id]
        solde = invoice.total_ttc - lettres.get(invoice.id, 0)
        if montant > solde:
            raise BusinessRuleError(
                "L'affectation dépasse le solde restant dû de la facture "
                f"numérotée {invoice.number} : restant {solde}, demandé {montant}."
            )


def create_payment(session: Session, actor: Actor, data: PaymentData) -> PurchasePayment:
    """Enregistre un décaissement et ses affectations (lettrage fournisseurs), en
    une transaction : exercice de la date de décaissement résolu d'abord, factures
    verrouillées ensuite, soldes contrôlés sous verrou, montant recalculé."""
    if not data.allocations:
        raise BusinessRuleError("Un règlement s'affecte à au moins une facture.")
    for allocation in data.allocations:
        if allocation.amount <= 0:
            raise BusinessRuleError(
                "Le montant de chaque affectation doit être strictement positif."
            )
    method = (data.method or "").strip()
    if method not in {m.value for m in PaymentMethod}:
        raise BusinessRuleError("Mode de paiement inconnu.")
    fiscal_year = _fiscal_year_for(session, actor.company_id, data.paid_on)
    invoices = _lock_invoices(session, actor.company_id, [a.document_id for a in data.allocations])
    _controlle_factures(session, actor, invoices, data.allocations)
    partner_id = invoices[0].partner_id
    company = session.get_one(Company, actor.company_id)
    payment = PurchasePayment(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        fiscal_year_id=fiscal_year.id,
        paid_on=data.paid_on,
        method=method,
        reference=_clean(data.reference),
        notes=_clean(data.notes),
        amount=sum(a.amount for a in data.allocations),
        currency=company.currency,
        partner_id=partner_id,
        created_by_user_id=actor.user_id,
    )
    session.add(payment)
    for allocation in data.allocations:
        session.add(
            PurchasePaymentAllocation(
                id=uuid.uuid4(),
                tenant_id=actor.company_id,
                payment_id=payment.id,
                document_id=allocation.document_id,
                amount=allocation.amount,
            )
        )
    record_event(
        session,
        action="purchase_payment.created",
        entity_type="purchase_payment",
        entity_id=payment.id,
        payload={
            "montant": payment.amount,
            "mode": payment.method,
            "factures": len(data.allocations),
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return payment


def delete_payment(session: Session, actor: Actor, payment_id: uuid.UUID) -> None:
    """Supprime un décaissement (correction d'erreur de saisie) : les affectations
    partent avec lui (CASCADE de la base — sans relation ORM, l'ordre de
    suppression parent/enfant appartient à PostgreSQL) et les soldes des
    factures sont libérés. Journalisé. Un règlement comptabilisé se corrige
    d'abord par la contre-passation de son écriture : tant qu'elle est vivante,
    la suppression détruirait de l'argent déjà porté au grand livre ; une fois
    contre-passée, le grand livre est corrigé et la trace opérationnelle erronée
    peut partir."""
    payment, _ = get_payment(session, actor.company_id, payment_id)
    if (
        payment.entry_id is not None
        and reversal_id_of(session, actor.company_id, payment.entry_id) is None
    ):
        raise ConflictError(
            "Ce règlement est comptabilisé : contre-passez son écriture "
            "(grand livre) avant de le supprimer."
        )
    montant, mode = payment.amount, payment.method
    session.delete(payment)
    record_event(
        session,
        action="purchase_payment.deleted",
        entity_type="purchase_payment",
        entity_id=payment_id,
        payload={"montant": montant, "mode": mode},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()


def list_payments(
    session: Session,
    company_id: uuid.UUID,
    *,
    partner_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PurchasePayment], int]:
    """Liste paginée et filtrée des décaissements ; renvoie (items, total)."""
    query = select(PurchasePayment).where(PurchasePayment.tenant_id == company_id)
    count = (
        select(func.count())
        .select_from(PurchasePayment)
        .where(PurchasePayment.tenant_id == company_id)
    )
    if partner_id is not None:
        query = query.where(PurchasePayment.partner_id == partner_id)
        count = count.where(PurchasePayment.partner_id == partner_id)
    if document_id is not None:
        lettres = select(PurchasePaymentAllocation.payment_id).where(
            PurchasePaymentAllocation.tenant_id == company_id,
            PurchasePaymentAllocation.document_id == document_id,
        )
        query = query.where(PurchasePayment.id.in_(lettres))
        count = count.where(PurchasePayment.id.in_(lettres))
    if date_from is not None:
        query = query.where(PurchasePayment.paid_on >= date_from)
        count = count.where(PurchasePayment.paid_on >= date_from)
    if date_to is not None:
        query = query.where(PurchasePayment.paid_on <= date_to)
        count = count.where(PurchasePayment.paid_on <= date_to)
    total = session.execute(count).scalar_one()
    items = list(
        session.execute(
            query.order_by(PurchasePayment.paid_on.desc(), PurchasePayment.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return items, total


def allocations_of_payments(
    session: Session, company_id: uuid.UUID, payment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[PurchasePaymentAllocation]]:
    """Affectations d'une page de règlements (une requête pour toute la page)."""
    if not payment_ids:
        return {}
    rows = list(
        session.execute(
            select(PurchasePaymentAllocation)
            .where(
                PurchasePaymentAllocation.tenant_id == company_id,
                PurchasePaymentAllocation.payment_id.in_(payment_ids),
            )
            .order_by(PurchasePaymentAllocation.document_id)
        ).scalars()
    )
    par_reglement: dict[uuid.UUID, list[PurchasePaymentAllocation]] = {}
    for row in rows:
        par_reglement.setdefault(row.payment_id, []).append(row)
    return par_reglement


@dataclass(frozen=True)
class AgingBucket:
    """Un bucket de l'échéancier : nombre de factures et somme des soldes."""

    count: int
    total_ttc: int


@dataclass(frozen=True)
class AgingReport:
    """Échéancier fournisseurs à une date donnée : buckets bornés (à-échoir,
    1-30, 31-60, 61-90, plus de 90 jours) et total général."""

    as_of: date
    buckets: dict[str, AgingBucket]
    grand_total_ttc: int


def payables_aging(session: Session, company_id: uuid.UUID, as_of: date) -> AgingReport:
    """Échéancier fournisseurs : factures d'achat émises non soldées, réparties
    par ancienneté de retard (échéance passée) au {as_of}. Un solde nul ou
    négatif (avoir excédentaire) n'entre pas."""
    invoices = list(
        session.execute(
            select(PurchaseDocument).where(
                PurchaseDocument.tenant_id == company_id,
                PurchaseDocument.doc_kind == PurchaseDocKind.SUPPLIER_INVOICE.value,
                PurchaseDocument.status == PurchaseDocStatus.ISSUED.value,
            )
        ).scalars()
    )
    lettres = outstanding_for_documents(session, company_id, [i.id for i in invoices])
    buckets: dict[str, AgingBucket] = {
        cle: AgingBucket(count=0, total_ttc=0)
        for cle in ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")
    }
    for invoice in invoices:
        solde = invoice.total_ttc - lettres.get(invoice.id, 0)
        if solde <= 0:
            continue
        retard = 0 if invoice.due_on is None else (as_of - invoice.due_on).days
        if retard <= 0:
            cle = "not_due"
        elif retard <= 30:
            cle = "d1_30"
        elif retard <= 60:
            cle = "d31_60"
        elif retard <= 90:
            cle = "d61_90"
        else:
            cle = "d90_plus"
        precedent = buckets[cle]
        buckets[cle] = AgingBucket(count=precedent.count + 1, total_ttc=precedent.total_ttc + solde)
    return AgingReport(
        as_of=as_of,
        buckets=buckets,
        grand_total_ttc=sum(b.total_ttc for b in buckets.values()),
    )
