"""Routes des achats : factures et avoirs fournisseurs (Phase 4F).

Le cycle de vie et la numérotation sans trou (FACH/AVF) miroivent les ventes ;
les décaissements et leur lettrage commercial portent le solde restant dû des
factures fournisseurs ; l'échéancier répartit les dettes par ancienneté de
retard. La comptabilisation est un acte explicite du comptable : elle crée et
valide l'écriture du grand livre qui porte le document ou le décaissement
(permission `entries:post`).
"""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, model_validator

from kora.accounting.entries import Actor
from kora.api.v1.common import WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.core.errors import ErrorResponse
from kora.models.common import utcnow
from kora.models.purchases import (
    PurchaseDocument,
    PurchaseDocumentLine,
    PurchasePayment,
    PurchasePaymentAllocation,
)
from kora.purchases import accounting, payments, service
from kora.purchases.payments import PaymentStatus
from kora.purchases.service import DocumentData, LineData
from kora.tenancy.deps import EntriesPost, PurchasesManage, PurchasesRead, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["achats"])

DocKindParam = Literal["supplier_invoice", "supplier_credit_note"]
DocStatusParam = Literal["DRAFT", "ISSUED", "CANCELLED"]
PaymentMethodParam = Literal["CASH", "BANK_TRANSFER", "MOBILE_MONEY", "CHECK", "CARD", "OTHER"]
PaymentStatusParam = Literal["none", "partial", "paid"]


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class PurchaseLineIn(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=200)]
    # Quantité en millièmes : 2,5 kg = 2500 (jamais de flottant).
    quantity: Annotated[int, Field(gt=0)]
    # Prix unitaire HT en unités mineures de la devise du dossier.
    unit_price_ht: Annotated[int, Field(ge=0)]
    discount_bp: Annotated[int, Field(default=0, ge=0, le=10_000)]
    tax_rate_id: uuid.UUID | None = None
    tax_exempt_reason: Annotated[str | None, Field(max_length=200)] = None


class PurchaseLineOut(BaseModel):
    line_no: int
    label: str
    quantity: int
    unit_price_ht: int
    discount_bp: int
    tax_rate_id: uuid.UUID | None
    tax_bp_snapshot: int | None
    tax_exempt_reason: str | None
    line_ht: int
    line_tax: int
    line_ttc: int


class PurchaseDocumentOut(BaseModel):
    id: uuid.UUID
    doc_kind: DocKindParam
    status: DocStatusParam
    number: int | None
    issued_on: str | None
    due_on: str | None
    partner_id: uuid.UUID
    reference: str | None
    currency: str
    total_ht: int
    total_tax: int
    total_ttc: int
    notes: str | None
    origin_document_id: uuid.UUID | None
    reverses_document_id: uuid.UUID | None
    created_at: str
    # Solde restant dû et statut de paiement : remplis uniquement pour une
    # facture émise ; None ailleurs (brouillon, avoir, facture annulée).
    outstanding_ttc: int | None = None
    payment_status: PaymentStatusParam | None = None
    # Écriture validée qui porte le document en comptabilité : NULL tant
    # que le comptable n'a pas comptabilisé — jamais automatique.
    entry_id: uuid.UUID | None = None


class PurchaseDocumentDetailOut(PurchaseDocumentOut):
    lines: list[PurchaseLineOut]
    partner_snapshot: dict[str, Any] | None
    issuer_snapshot: dict[str, Any] | None


class PurchaseDocumentsOut(BaseModel):
    items: list[PurchaseDocumentOut]
    total: int


class PurchaseDocumentIssuedOut(BaseModel):
    """Résultat d'une numérotation définitive : document émis et mentions
    complémentaires manquantes signalées (non bloquant)."""

    document: PurchaseDocumentDetailOut
    warnings: list[str]


class PurchaseDocumentCreate(RequestBody):
    doc_kind: DocKindParam
    partner_id: uuid.UUID
    lines: Annotated[list[PurchaseLineIn], Field(min_length=1, max_length=50)]
    due_on: date | None = None
    notes: str | None = None
    # Numéro imprimé sur la facture du fournisseur (pièce justificative).
    reference: Annotated[str | None, Field(max_length=100)] = None
    origin_document_id: uuid.UUID | None = None
    reverses_document_id: uuid.UUID | None = None


class PurchaseDocumentUpdate(RequestBody):
    """PATCH partiel d'un brouillon : seuls les champs fournis sont modifiés ;
    « lines » remplace intégralement les lignes."""

    due_on: date | None = None
    notes: str | None = None
    reference: Annotated[str | None, Field(max_length=100)] = None
    lines: Annotated[list[PurchaseLineIn] | None, Field(min_length=1, max_length=50)] = None

    @model_validator(mode="after")
    def _not_empty(self) -> "PurchaseDocumentUpdate":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self


class PurchaseIssueIn(RequestBody):
    """Émission avec date explicite facultative (rattrapage de saisie) : la date
    doit tomber dans un exercice ouvert, hors période verrouillée."""

    issued_on: date | None = None


class PurchaseDocumentEntryIn(RequestBody):
    """Comptabilisation d'un document émis : le compte de charge est choisi par
    le comptable (défaut : numéro 601 du plan du dossier) ; la TVA suit les
    comptes récupérables des taux figés à l'émission."""

    expense_account_id: uuid.UUID | None = None


class PurchasePaymentEntryIn(RequestBody):
    """Comptabilisation d'un décaissement : le compte de trésorerie est choisi
    par le comptable (défaut : 571 pour la caisse, 521 pour les autres modes)."""

    cash_account_id: uuid.UUID | None = None


def _data(body: PurchaseDocumentCreate) -> DocumentData:
    return DocumentData(
        doc_kind=body.doc_kind,
        partner_id=body.partner_id,
        lines=tuple(
            LineData(
                label=line.label,
                quantity=line.quantity,
                unit_price_ht=line.unit_price_ht,
                discount_bp=line.discount_bp,
                tax_rate_id=line.tax_rate_id,
                tax_exempt_reason=line.tax_exempt_reason,
            )
            for line in body.lines
        ),
        due_on=body.due_on,
        notes=body.notes,
        reference=body.reference,
        origin_document_id=body.origin_document_id,
        reverses_document_id=body.reverses_document_id,
    )


def _line_out(line: PurchaseDocumentLine) -> PurchaseLineOut:
    return PurchaseLineOut(
        line_no=line.line_no,
        label=line.label,
        quantity=line.quantity,
        unit_price_ht=line.unit_price_ht,
        discount_bp=line.discount_bp,
        tax_rate_id=line.tax_rate_id,
        tax_bp_snapshot=line.tax_bp_snapshot,
        tax_exempt_reason=line.tax_exempt_reason,
        line_ht=line.line_ht,
        line_tax=line.line_tax,
        line_ttc=line.line_ttc,
    )


def _out(
    document: PurchaseDocument,
    lettres: dict[uuid.UUID, int] | None = None,
) -> PurchaseDocumentOut:
    outstanding: int | None = None
    payment_status: PaymentStatus | None = None
    if document.doc_kind == "supplier_invoice" and document.status == "ISSUED":
        credited = (lettres or {}).get(document.id, 0)
        outstanding = document.total_ttc - credited
        payment_status = payments.payment_status_for(outstanding, document.total_ttc)
    return PurchaseDocumentOut(
        id=document.id,
        doc_kind=document.doc_kind,
        status=document.status,
        number=document.number,
        issued_on=document.issued_on.isoformat() if document.issued_on else None,
        due_on=document.due_on.isoformat() if document.due_on else None,
        partner_id=document.partner_id,
        reference=document.reference,
        currency=document.currency,
        total_ht=document.total_ht,
        total_tax=document.total_tax,
        total_ttc=document.total_ttc,
        notes=document.notes,
        origin_document_id=document.origin_document_id,
        reverses_document_id=document.reverses_document_id,
        created_at=document.created_at.isoformat(),
        outstanding_ttc=outstanding,
        payment_status=payment_status,
        entry_id=document.entry_id,
    )


def _detail_out(
    document: PurchaseDocument,
    lines: list[PurchaseDocumentLine],
    lettres: dict[uuid.UUID, int] | None = None,
) -> PurchaseDocumentDetailOut:
    return PurchaseDocumentDetailOut(
        **_out(document, lettres).model_dump(),
        lines=[_line_out(line) for line in lines],
        partner_snapshot=document.partner_snapshot,
        issuer_snapshot=document.issuer_snapshot,
    )


def _lettres(
    db: DbSession, company_id: uuid.UUID, document: PurchaseDocument
) -> dict[uuid.UUID, int]:
    """Sommes lettrées d'un document unique (détail et mutations) : une requête."""
    return payments.outstanding_for_documents(db, company_id, [document.id])


@router.get("/purchases", responses={404: {"model": ErrorResponse}})
def list_documents(
    tenant: PurchasesRead,
    db: DbSession,
    kind: DocKindParam | None = None,
    status_filter: Annotated[DocStatusParam | None, Query(alias="status")] = None,
    partner_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PurchaseDocumentsOut:
    """Factures et avoirs fournisseurs du dossier, filtrables et paginés."""
    items, total = service.list_documents(
        db,
        tenant.company_id,
        doc_kind=kind,
        status=status_filter,
        partner_id=partner_id,
        search=q,
        limit=limit,
        offset=offset,
    )
    lettres = payments.outstanding_for_documents(db, tenant.company_id, [d.id for d in items])
    return PurchaseDocumentsOut(items=[_out(d, lettres) for d in items], total=total)


@router.post("/purchases", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_document(
    body: PurchaseDocumentCreate, tenant: PurchasesManage, db: DbSession, ctx: Ctx
) -> PurchaseDocumentDetailOut:
    created = service.create_document(db, _actor(tenant, ctx), _data(body))
    document, lines = service.get_document(db, tenant.company_id, created.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.get("/purchases/{document_id}", responses={404: {"model": ErrorResponse}})
def get_document(
    document_id: uuid.UUID, tenant: PurchasesRead, db: DbSession
) -> PurchaseDocumentDetailOut:
    document, lines = service.get_document(db, tenant.company_id, document_id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.patch("/purchases/{document_id}", responses=WRITE_ERRORS)
def update_document(
    document_id: uuid.UUID,
    body: PurchaseDocumentUpdate,
    tenant: PurchasesManage,
    db: DbSession,
    ctx: Ctx,
) -> PurchaseDocumentDetailOut:
    changes: dict[str, object] = body.model_dump(exclude_unset=True, exclude={"lines"})
    if body.lines is not None:
        changes["lines"] = tuple(
            LineData(
                label=line.label,
                quantity=line.quantity,
                unit_price_ht=line.unit_price_ht,
                discount_bp=line.discount_bp,
                tax_rate_id=line.tax_rate_id,
                tax_exempt_reason=line.tax_exempt_reason,
            )
            for line in body.lines
        )
    updated = service.update_draft(db, _actor(tenant, ctx), document_id, changes)
    document, lines = service.get_document(db, tenant.company_id, updated.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.delete("/purchases/{document_id}", status_code=204, responses=WRITE_ERRORS)
def delete_document(
    document_id: uuid.UUID, tenant: PurchasesManage, db: DbSession, ctx: Ctx
) -> None:
    service.delete_draft(db, _actor(tenant, ctx), document_id)


@router.post("/purchases/{document_id}/issue", responses=WRITE_ERRORS)
def issue_document(
    document_id: uuid.UUID,
    tenant: PurchasesManage,
    db: DbSession,
    ctx: Ctx,
    body: PurchaseIssueIn | None = None,
) -> PurchaseDocumentIssuedOut:
    """Numérotation définitive d'une facture ou d'un avoir fournisseur :
    irréversible, sans trou."""
    issued_on = body.issued_on if body is not None else None
    document, warnings = service.issue_document(
        db, _actor(tenant, ctx), document_id, issued_on=issued_on
    )
    _, lines = service.get_document(db, tenant.company_id, document.id)
    return PurchaseDocumentIssuedOut(
        document=_detail_out(document, lines, _lettres(db, tenant.company_id, document)),
        warnings=warnings,
    )


@router.post("/purchases/{document_id}/cancel", responses=WRITE_ERRORS)
def cancel_invoice(
    document_id: uuid.UUID, tenant: PurchasesManage, db: DbSession, ctx: Ctx
) -> PurchaseDocumentDetailOut:
    """Annulation d'une facture fournisseur émise sans avoir : le numéro est
    conservé."""
    cancelled = service.cancel_supplier_invoice(db, _actor(tenant, ctx), document_id)
    document, lines = service.get_document(db, tenant.company_id, cancelled.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


# --- Décaissements fournisseurs et lettrage commercial -------------------------


class PurchaseAllocationIn(BaseModel):
    document_id: uuid.UUID
    amount: Annotated[int, Field(gt=0)]


class PurchasePaymentIn(RequestBody):
    """Décaissement saisi : le montant n'est jamais transmis — c'est la somme
    des affectations que le service recalcule et contrôle sous verrou."""

    paid_on: date
    method: PaymentMethodParam
    allocations: Annotated[list[PurchaseAllocationIn], Field(min_length=1, max_length=50)]
    reference: Annotated[str | None, Field(max_length=100)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None


class PurchaseAllocationOut(BaseModel):
    document_id: uuid.UUID
    amount: int


class PurchasePaymentOut(BaseModel):
    id: uuid.UUID
    paid_on: str
    method: PaymentMethodParam
    reference: str | None
    notes: str | None
    amount: int
    currency: str
    partner_id: uuid.UUID
    fiscal_year_id: uuid.UUID
    created_at: str
    allocations: list[PurchaseAllocationOut]
    # Écriture validée qui porte le décaissement en comptabilité.
    entry_id: uuid.UUID | None = None


class PurchasePaymentsOut(BaseModel):
    items: list[PurchasePaymentOut]
    total: int


class PayablesAgingBucketOut(BaseModel):
    count: int
    total_ttc: int


class PayablesAgingOut(BaseModel):
    """Échéancier fournisseurs : dettes d'achat émises non soldées par
    ancienneté de retard."""

    as_of: str
    buckets: dict[str, PayablesAgingBucketOut]
    grand_total_ttc: int


def _payment_data(body: PurchasePaymentIn) -> payments.PaymentData:
    return payments.PaymentData(
        paid_on=body.paid_on,
        method=body.method,
        allocations=tuple(
            payments.AllocationData(document_id=a.document_id, amount=a.amount)
            for a in body.allocations
        ),
        reference=body.reference,
        notes=body.notes,
    )


def _payment_out(
    payment: PurchasePayment, allocations: list[PurchasePaymentAllocation]
) -> PurchasePaymentOut:
    return PurchasePaymentOut(
        id=payment.id,
        paid_on=payment.paid_on.isoformat(),
        method=payment.method,
        reference=payment.reference,
        notes=payment.notes,
        amount=payment.amount,
        currency=payment.currency,
        partner_id=payment.partner_id,
        fiscal_year_id=payment.fiscal_year_id,
        created_at=payment.created_at.isoformat(),
        allocations=[
            PurchaseAllocationOut(document_id=a.document_id, amount=a.amount) for a in allocations
        ],
        entry_id=payment.entry_id,
    )


@router.get("/purchase-payments", responses={404: {"model": ErrorResponse}})
def list_payments(
    tenant: PurchasesRead,
    db: DbSession,
    partner_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PurchasePaymentsOut:
    """Décaissements du dossier (règlements fournisseurs lettrés), filtrables
    et paginés."""
    items, total = payments.list_payments(
        db,
        tenant.company_id,
        partner_id=partner_id,
        document_id=document_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    par_reglement = payments.allocations_of_payments(db, tenant.company_id, [p.id for p in items])
    return PurchasePaymentsOut(
        items=[_payment_out(p, par_reglement.get(p.id, [])) for p in items],
        total=total,
    )


@router.post("/purchase-payments", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_payment(
    body: PurchasePaymentIn, tenant: PurchasesManage, db: DbSession, ctx: Ctx
) -> PurchasePaymentOut:
    """Enregistre un décaissement fournisseur et son lettrage : le solde des
    factures visées est contrôlé sous verrou — jamais d'affectation au-delà du
    restant dû."""
    created = payments.create_payment(db, _actor(tenant, ctx), _payment_data(body))
    payment, allocations = payments.get_payment(db, tenant.company_id, created.id)
    return _payment_out(payment, allocations)


@router.get("/purchase-payments/{payment_id}", responses={404: {"model": ErrorResponse}})
def get_payment(payment_id: uuid.UUID, tenant: PurchasesRead, db: DbSession) -> PurchasePaymentOut:
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    return _payment_out(payment, allocations)


@router.delete("/purchase-payments/{payment_id}", status_code=204, responses=WRITE_ERRORS)
def delete_payment(payment_id: uuid.UUID, tenant: PurchasesManage, db: DbSession, ctx: Ctx) -> None:
    """Supprime un décaissement (correction de saisie) : les soldes des factures
    sont libérés et l'action est journalisée. Refusé tant que le règlement est
    comptabilisé : l'écriture se contre-passe d'abord au grand livre."""
    payments.delete_payment(db, _actor(tenant, ctx), payment_id)


@router.post("/purchases/{document_id}/entry", responses=WRITE_ERRORS)
def post_document_entry(
    document_id: uuid.UUID,
    body: PurchaseDocumentEntryIn,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> PurchaseDocumentDetailOut:
    """Comptabilise une facture ou un avoir fournisseur émis : écriture validée
    du journal des achats (débit du compte de charge au HT, débit des comptes
    récupérables par taux, crédit du compte de tiers au TTC — inversée pour un
    avoir), liée au document. Idempotence refusée : un document déjà
    comptabilisé répond 409."""
    accounting.post_document(
        db,
        _actor(tenant, ctx),
        document_id,
        expense_account_id=body.expense_account_id,
    )
    document, lines = service.get_document(db, tenant.company_id, document_id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.post("/purchase-payments/{payment_id}/entry", responses=WRITE_ERRORS)
def post_payment_entry(
    payment_id: uuid.UUID,
    body: PurchasePaymentEntryIn,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> PurchasePaymentOut:
    """Comptabilise un décaissement : écriture validée du journal de trésorerie
    (débit du compte de tiers, crédit du compte de trésorerie), liée au
    règlement. Idempotence refusée : un règlement déjà comptabilisé répond 409."""
    accounting.post_payment(
        db,
        _actor(tenant, ctx),
        payment_id,
        cash_account_id=body.cash_account_id,
    )
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    return _payment_out(payment, allocations)


@router.get("/payables/aging", responses={404: {"model": ErrorResponse}})
def payables_aging(
    tenant: PurchasesRead,
    db: DbSession,
    as_of: date | None = None,
) -> PayablesAgingOut:
    """Échéancier fournisseurs : factures d'achat émises non soldées, par
    ancienneté de retard au jour demandé (aujourd'hui par défaut)."""
    body = payments.payables_aging(db, tenant.company_id, as_of or utcnow().date())
    return PayablesAgingOut(
        as_of=body.as_of.isoformat(),
        buckets={
            cle: PayablesAgingBucketOut(count=b.count, total_ttc=b.total_ttc)
            for cle, b in body.buckets.items()
        },
        grand_total_ttc=body.grand_total_ttc,
    )
