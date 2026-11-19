"""Décaissements fournisseurs, avances et lettrage commercial des achats
(Phase 4F, lot B-3).

Règles portées par le service (et la base quand possible) — miroir exact du
module ventes (Phase 4C, lot B-3) :
- un décaissement sort de l'argent : montant strictement positif, au moins égal
  à la somme de ses affectations (le service la recalcule — jamais saisie par
  l'appelant) ; la différence est le **reste non affecté** : avance versée sans
  facture (affectations vides, tier fournisseur exigé) ou trop-versé sur une
  facture — remboursable et affectable ultérieurement, jamais comptabilisé
  comme un décaissement lettré ;
- une affectation vise une facture fournisseur émise du même tier et de la
  même devise ; le montant ne dépasse jamais le solde restant dû (TTC -
  affectations - avoirs partiels émis), contrôlé sous verrou FOR UPDATE de la
  facture : deux règlements concurrents ne peuvent pas excéder le TTC ensemble ;
- **l'affectation ultérieure** (lot B-3) ajoute des affectations à un
  règlement existant sur son reste non affecté : cibles exprimées en montants
  cibles absolus par facture (répéter la même demande ne change rien —
  idempotence), hausse seule permise (la réduction passe par la suppression du
  règlement, traçable au journal d'audit) ; somme cible ≤ montant -
  remboursements, jamais au-delà (aucun double emploi de la même avance) ;
- la date de décaissement tombe dans un exercice ouvert (même règle que les
  documents d'achat) ;
- le règlement est immuable après création : une erreur se corrige en le
  supprimant (journalisé) puis en le re-saisissant ; supprimer un règlement
  libère le solde des factures qu'il lettrait ;
- **le remboursement** (lot B-3) constate le retour d'une part du reste non
  affecté (le fournisseur rend l'avance) : montant ≤ disponible (montant -
  affectations - remboursements saisis), immuable après création, supprimable
  tant que non comptabilisé ;
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
  4A, 4B, 4C, 4D et 4F.
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
from kora.models.partners import Partner
from kora.models.purchases import (
    PurchaseDocKind,
    PurchaseDocStatus,
    PurchaseDocument,
    PurchasePayment,
    PurchasePaymentAllocation,
    PurchaseRefund,
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
    Le montant n'est saisi que pour une avance ou un trop-versé : il doit être
    au moins égal à la somme des affectations (recalculée et contrôlée sous
    verrou) ; la différence est le reste non affecté. Sans montant, le
    règlement est intégralement lettré (comportement historique)."""

    paid_on: date
    method: str
    allocations: tuple[AllocationData, ...]
    reference: str | None = None
    notes: str | None = None
    amount: int | None = None
    partner_id: uuid.UUID | None = None


@dataclass(frozen=True)
class RefundData:
    """Remboursement saisi : la date (fait générateur), le mode, le montant en
    unités mineures — borné au reste non affecté du règlement porteur."""

    refunded_on: date
    method: str
    amount: int
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
    verrouillées ensuite, soldes contrôlés sous verrou, montant contrôlé.

    Sans affectation, le décaissement est une **avance** : le montant saisi est
    obligatoire (strictement positif) et le tier fournisseur aussi — l'argent
    versé reste non affecté jusqu'à l'affectation ultérieure ou au remboursement.
    Avec affectations, le montant saisi (facultatif) doit être au moins égal à
    leur somme : l'excédent devient un trop-versé non lettré."""
    somme = 0
    for allocation in data.allocations:
        if allocation.amount <= 0:
            raise BusinessRuleError(
                "Le montant de chaque affectation doit être strictement positif."
            )
        somme += allocation.amount
    method = (data.method or "").strip()
    if method not in {m.value for m in PaymentMethod}:
        raise BusinessRuleError("Mode de paiement inconnu.")
    company = session.get_one(Company, actor.company_id)
    if data.amount is not None and data.amount <= 0:
        raise BusinessRuleError("Le montant du règlement doit être strictement positif.")
    if data.amount is not None and data.amount < somme:
        raise BusinessRuleError(
            f"Le montant saisi ({data.amount}) est inférieur à la somme des "
            f"affectations ({somme}) : un règlement ne lettre jamais plus que ce qu'il verse."
        )
    if not data.allocations:
        partner_id = _resoudre_avance(session, actor, data)
    else:
        invoices = _lock_invoices(
            session, actor.company_id, [a.document_id for a in data.allocations]
        )
        _controlle_factures(session, actor, invoices, data.allocations)
        partner_id = invoices[0].partner_id
        if data.partner_id is not None and data.partner_id != partner_id:
            raise BusinessRuleError(
                "Le tier saisi ne correspond pas aux factures visées : un "
                "règlement s'affecte aux factures d'un seul tier."
            )
    # Exercice de la date de décaissement : résolu après les contrôles de saisie
    # (identique pour l'avance et le règlement lettré).
    fiscal_year = _fiscal_year_for(session, actor.company_id, data.paid_on)
    amount = data.amount if data.amount is not None else somme
    payment = PurchasePayment(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        fiscal_year_id=fiscal_year.id,
        paid_on=data.paid_on,
        method=method,
        reference=_clean(data.reference),
        notes=_clean(data.notes),
        amount=amount,
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
            "non_affecte": amount - somme,
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
    rembourse_vivant = [
        refund.id
        for refund in refunds_of_payments(session, actor.company_id, [payment.id]).get(
            payment.id, []
        )
        if refund.entry_id is not None
        and reversal_id_of(session, actor.company_id, refund.entry_id) is None
    ]
    if rembourse_vivant:
        raise ConflictError(
            "Ce règlement porte un remboursement comptabilisé : contre-passez "
            "son écriture (grand livre) avant de le supprimer."
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


def refunds_of_payments(
    session: Session, company_id: uuid.UUID, payment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[PurchaseRefund]]:
    """Remboursements d'une page de règlements (une requête pour toute la page)."""
    if not payment_ids:
        return {}
    rows = list(
        session.execute(
            select(PurchaseRefund)
            .where(
                PurchaseRefund.tenant_id == company_id,
                PurchaseRefund.payment_id.in_(payment_ids),
            )
            .order_by(PurchaseRefund.refunded_on, PurchaseRefund.created_at)
        ).scalars()
    )
    par_reglement: dict[uuid.UUID, list[PurchaseRefund]] = {}
    for row in rows:
        par_reglement.setdefault(row.payment_id, []).append(row)
    return par_reglement


def unallocated_of(
    payment: PurchasePayment,
    allocations: list[PurchasePaymentAllocation],
    refunds: list[PurchaseRefund],
) -> int:
    """Reste non affecté d'un règlement : montant - affectations - remboursements.
    Calculé en lecture : aucun statut dérivé stocké, aucune dérive possible. La
    somme affectations + remboursements ne dépasse jamais le montant (invariant
    contrôlé sous verrou par chaque mutation) — le reste reste positif."""
    return payment.amount - sum(a.amount for a in allocations) - sum(r.amount for r in refunds)


def _resoudre_avance(session: Session, actor: Actor, data: PaymentData) -> uuid.UUID:
    """Valide la saisie d'une **avance** (décaissement sans facture visée) : le
    montant saisi est obligatoire et le tier fournisseur aussi — l'argent versé
    reste non affecté jusqu'à l'affectation ultérieure ou au remboursement.
    Renvoie l'identifiant du tier fournisseur."""
    if data.amount is None:
        raise BusinessRuleError(
            "Une avance exige un montant saisi : sans facture visée, le "
            "règlement n'a rien à lettrer."
        )
    if data.partner_id is None:
        raise BusinessRuleError("Une avance exige le tier fournisseur qui la reçoit.")
    partner = session.execute(
        select(Partner).where(Partner.tenant_id == actor.company_id, Partner.id == data.partner_id)
    ).scalar_one_or_none()
    if partner is None:
        raise NotFoundError("Tier introuvable dans ce dossier.")
    if not partner.is_supplier:
        raise BusinessRuleError(
            "Une avance fournisseur se verse à un tier fournisseur : cochez le "
            "tier comme fournisseur (Référentiel) d'abord."
        )
    return data.partner_id


def _cibles_valides(
    targets: tuple[AllocationData, ...], existantes: dict[uuid.UUID, PurchasePaymentAllocation]
) -> None:
    """Cibles d'affectation ultérieure : montants strictement positifs, jamais
    inférieurs à l'affectation déjà en place (la réduction passerait par la
    suppression du règlement — traçable au journal d'audit). Une cible égale à
    l'existant est un no-op idempotent (l'état atteint ne change pas)."""
    for target in targets:
        if target.amount <= 0:
            raise BusinessRuleError(
                "Le montant cible de chaque affectation doit être strictement positif."
            )
        deja = existantes.get(target.document_id)
        if deja is not None and target.amount < deja.amount:
            raise BusinessRuleError(
                "L'affectation ne se réduit pas : supprimez le règlement "
                "(correction de saisie) puis re-saisissez-le."
            )


def _controlle_cibles(
    session: Session,
    actor: Actor,
    payment: PurchasePayment,
    factures: list[PurchaseDocument],
) -> None:
    """Factures visées par l'affectation ultérieure : type facture, statut émis,
    tier du règlement et devise du dossier — même discipline qu'à la création."""
    company = session.get_one(Company, actor.company_id)
    for invoice in factures:
        if invoice.doc_kind != PurchaseDocKind.SUPPLIER_INVOICE.value:
            raise BusinessRuleError(
                "L'affectation ultérieure ne vise qu'une facture (pas un devis ni un avoir)."
            )
        if invoice.status != PurchaseDocStatus.ISSUED.value:
            raise ConflictError("Seule une facture émise peut recevoir une affectation.")
        if invoice.partner_id != payment.partner_id:
            raise BusinessRuleError(
                "L'affectation ultérieure vise les factures du tier du règlement."
            )
        if invoice.currency != company.currency:
            raise BusinessRuleError(
                "L'affectation ultérieure vise des factures de la devise du dossier."
            )


def _deltas_cibles(
    session: Session,
    actor: Actor,
    payment: PurchasePayment,
    factures: list[PurchaseDocument],
    targets: tuple[AllocationData, ...],
    *,
    existantes: dict[uuid.UUID, PurchasePaymentAllocation],
) -> dict[uuid.UUID, int]:
    """Hausse par facture (delta entre la cible et l'existant), sous double
    contrôle : l'invariant du règlement d'abord (somme cible ≤ montant -
    remboursements — la même avance ne se dépense jamais deux fois), le solde
    restant dû de chaque facture ensuite (delta ≤ solde, sous verrou — deux
    affectations concurrentes ne peuvent jamais excéder le TTC ensemble)."""
    cible_totale = 0
    for target in targets:
        deja = existantes.get(target.document_id)
        actuel = deja.amount if deja is not None else 0
        cible_totale += actuel + max(target.amount - actuel, 0)
    rembourses = sum(
        r.amount
        for r in refunds_of_payments(session, actor.company_id, [payment.id]).get(payment.id, [])
    )
    if cible_totale > payment.amount - rembourses:
        raise BusinessRuleError(
            f"Les cibles dépassent le disponible du règlement : total visé "
            f"{cible_totale}, disponible {payment.amount - rembourses} "
            f"(montant {payment.amount} - remboursements {rembourses})."
        )
    lettres = outstanding_for_documents(
        session, actor.company_id, [invoice.id for invoice in factures]
    )
    deltas: dict[uuid.UUID, int] = {}
    for invoice in factures:
        target = next(t for t in targets if t.document_id == invoice.id)
        deja = existantes.get(invoice.id)
        delta = target.amount - (deja.amount if deja is not None else 0)
        if delta <= 0:
            continue
        solde = invoice.total_ttc - lettres.get(invoice.id, 0)
        if delta > solde:
            raise BusinessRuleError(
                f"L'affectation dépasse le solde restant dû de la facture "
                f"numérotée {invoice.number} : restant {solde}, hausse demandée {delta}."
            )
        deltas[invoice.id] = delta
    return deltas


def allocate_payment(
    session: Session,
    actor: Actor,
    payment_id: uuid.UUID,
    targets: tuple[AllocationData, ...],
) -> tuple[PurchasePayment, list[PurchasePaymentAllocation]]:
    """**Affectation ultérieure** (lot B-3) : affecte le reste non affecté d'un
    règlement (avance ou trop-versé) à des factures fournisseurs émises du même
    tier.

    Les cibles sont exprimées en **montants cibles absolus** par facture :
    répéter la même demande ne change rien (idempotence — la réponse porte
    l'état atteint) ; seule la hausse est permise (une réduction passerait par
    la suppression du règlement, traçable au journal d'audit). Contrôles sous
    verrou du règlement puis des factures visées (_cibles_valides,
    _controlle_cibles, _deltas_cibles). L'écriture de couverture (débit du
    compte de tiers fournisseur) reste à la comptabilisation : si le règlement
    est déjà comptabilisé, l'affectation ajoutée est non couverte (`entry_id`
    NULL) — le comptable poste le transfert d'avance (débit 401x, crédit 4091)
    explicitement."""
    if not targets:
        raise BusinessRuleError("L'affectation ultérieure vise au moins une facture.")
    payment = session.execute(
        select(PurchasePayment)
        .where(PurchasePayment.tenant_id == actor.company_id, PurchasePayment.id == payment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    existantes = {
        row.document_id: row
        for row in session.execute(
            select(PurchasePaymentAllocation).where(
                PurchasePaymentAllocation.payment_id == payment.id
            )
        ).scalars()
    }
    _cibles_valides(targets, existantes)
    factures = _lock_invoices(session, actor.company_id, [t.document_id for t in targets])
    _controlle_cibles(session, actor, payment, factures)
    deja_lettrees = sum(a.amount for a in existantes.values())
    deltas = _deltas_cibles(session, actor, payment, factures, targets, existantes=existantes)
    if not deltas:
        return payment, sorted(existantes.values(), key=lambda row: row.document_id)
    for invoice_id, delta in deltas.items():
        deja = existantes.get(invoice_id)
        if deja is None:
            session.add(
                PurchasePaymentAllocation(
                    id=uuid.uuid4(),
                    tenant_id=actor.company_id,
                    payment_id=payment.id,
                    document_id=invoice_id,
                    amount=delta,
                )
            )
        else:
            deja.amount += delta
    record_event(
        session,
        action="purchase_payment.allocations_added",
        entity_type="purchase_payment",
        entity_id=payment.id,
        payload={
            "cibles": {str(t.document_id): t.amount for t in targets},
            "ajoute": sum(deltas.values()),
            "lettres_avant": deja_lettrees,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    mises_a_jour = list(
        session.execute(
            select(PurchasePaymentAllocation)
            .where(PurchasePaymentAllocation.payment_id == payment.id)
            .order_by(PurchasePaymentAllocation.document_id)
        ).scalars()
    )
    return payment, mises_a_jour


def refund_payment(
    session: Session, actor: Actor, payment_id: uuid.UUID, data: RefundData
) -> PurchaseRefund:
    """**Remboursement** (lot B-3) : constate le retour d'une part du reste non
    affecté d'un règlement (avance ou trop-versé que le fournisseur rend). Le
    disponible est contrôlé sous verrou du règlement : montant - affectations -
    remboursements déjà saisis — la même avance ne se rembourse jamais deux
    fois. Aucune écriture ici : la comptabilisation (débit trésorerie, crédit
    4091) reste explicite."""
    if data.amount <= 0:
        raise BusinessRuleError("Le montant du remboursement doit être strictement positif.")
    method = (data.method or "").strip()
    if method not in {m.value for m in PaymentMethod}:
        raise BusinessRuleError("Mode de paiement inconnu.")
    payment = session.execute(
        select(PurchasePayment)
        .where(PurchasePayment.tenant_id == actor.company_id, PurchasePayment.id == payment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    disponible = unallocated_of(
        payment,
        list(
            session.execute(
                select(PurchasePaymentAllocation).where(
                    PurchasePaymentAllocation.payment_id == payment.id
                )
            ).scalars()
        ),
        refunds_of_payments(session, actor.company_id, [payment.id]).get(payment.id, []),
    )
    if data.amount > disponible:
        raise BusinessRuleError(
            f"Le remboursement dépasse le reste non affecté du règlement : "
            f"disponible {disponible}, demandé {data.amount}."
        )
    fiscal_year = _fiscal_year_for(session, actor.company_id, data.refunded_on)
    refund = PurchaseRefund(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        payment_id=payment.id,
        fiscal_year_id=fiscal_year.id,
        refunded_on=data.refunded_on,
        method=method,
        reference=_clean(data.reference),
        notes=_clean(data.notes),
        amount=data.amount,
        currency=payment.currency,
        created_by_user_id=actor.user_id,
    )
    session.add(refund)
    session.flush()
    record_event(
        session,
        action="purchase_payment.refunded",
        entity_type="purchase_refund",
        entity_id=refund.id,
        payload={
            "montant": refund.amount,
            "mode": refund.method,
            "reglement": str(payment.id),
            "reste_non_affecte": disponible - refund.amount,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return refund


def get_refund(session: Session, company_id: uuid.UUID, refund_id: uuid.UUID) -> PurchaseRefund:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    refund = session.execute(
        select(PurchaseRefund).where(
            PurchaseRefund.tenant_id == company_id, PurchaseRefund.id == refund_id
        )
    ).scalar_one_or_none()
    if refund is None:
        raise NotFoundError("Remboursement introuvable dans ce dossier.")
    return refund


def delete_refund(session: Session, actor: Actor, refund_id: uuid.UUID) -> None:
    """Supprime un remboursement (correction d'erreur de saisie) : le disponible
    du règlement porteur est restitué. Journalisé. Un remboursement comptabilisé
    se corrige d'abord par la contre-passation de son écriture : tant qu'elle
    est vivante, la suppression détruirait un mouvement déjà au grand livre."""
    refund = session.execute(
        select(PurchaseRefund).where(
            PurchaseRefund.tenant_id == actor.company_id, PurchaseRefund.id == refund_id
        )
    ).scalar_one_or_none()
    if refund is None:
        raise NotFoundError("Remboursement introuvable dans ce dossier.")
    if (
        refund.entry_id is not None
        and reversal_id_of(session, actor.company_id, refund.entry_id) is None
    ):
        raise ConflictError(
            "Ce remboursement est comptabilisé : contre-passez son écriture "
            "(grand livre) avant de le supprimer."
        )
    montant, reglement = refund.amount, refund.payment_id
    session.delete(refund)
    record_event(
        session,
        action="purchase_refund.deleted",
        entity_type="purchase_refund",
        entity_id=refund_id,
        payload={"montant": montant, "reglement": str(reglement)},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()


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
