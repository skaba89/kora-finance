"""Routes des devis, factures et avoirs : cycle de vie et numérotation sans trou (4B).

Le PDF conforme d'un document numéroté (4B-bis) est servi en fichier binaire avec
les mentions légales figées à la numérotation. Les règlements clients et leur
lettrage commercial (4C) portent le solde restant dû des factures ; la balance
âgée répartit les créances par ancienneté de retard. La comptabilisation (4E)
est un acte explicite du comptable : elle crée et valide l'écriture du grand
livre qui porte le document ou le règlement (permission `entries:post`)."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, EmailStr, Field, model_validator

from kora.accounting.entries import Actor
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.core.errors import ErrorResponse
from kora.exports import service as export_service
from kora.models.common import utcnow
from kora.models.sales import (
    SalesDocument,
    SalesDocumentEmail,
    SalesDocumentLine,
    SalesPayment,
    SalesPaymentAllocation,
    SalesRefund,
    SalesReminder,
    SalesReminderPolicy,
)
from kora.sales import (
    accounting,
    auto_reminders,
    collections,
    document_emails,
    payments,
    reminders,
    schedules,
    service,
)
from kora.sales.service import DocumentData, LineData
from kora.tenancy.deps import EntriesPost, SalesManage, SalesRead, TenantContext
from kora.worker.enqueue import enqueue_best_effort
from kora.worker.tasks import send_sales_document_email, send_sales_reminder

router = APIRouter(prefix="/companies/{company_id}", tags=["ventes"])

DocKindParam = Literal["quote", "invoice", "credit_note"]
DocStatusParam = Literal["DRAFT", "SENT", "ACCEPTED", "REJECTED", "ISSUED", "CANCELLED"]
PaymentMethodParam = Literal["CASH", "BANK_TRANSFER", "MOBILE_MONEY", "CHECK", "CARD", "OTHER"]
PaymentStatusParam = Literal["none", "partial", "paid"]


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class LineIn(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=200)]
    # Quantité en millièmes : 2,5 heures = 2500 (jamais de flottant).
    quantity: Annotated[int, Field(gt=0)]
    # Prix unitaire HT en unités mineures de la devise du dossier.
    unit_price_ht: Annotated[int, Field(ge=0)]
    discount_bp: Annotated[int, Field(default=0, ge=0, le=10_000)]
    tax_rate_id: uuid.UUID | None = None
    tax_exempt_reason: Annotated[str | None, Field(max_length=200)] = None


class LineOut(BaseModel):
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


class DocumentOut(BaseModel):
    id: uuid.UUID
    doc_kind: DocKindParam
    status: DocStatusParam
    number: int | None
    issued_on: str | None
    due_on: str | None
    valid_until: str | None
    partner_id: uuid.UUID
    currency: str
    total_ht: int
    total_tax: int
    total_ttc: int
    notes: str | None
    origin_document_id: uuid.UUID | None
    reverses_document_id: uuid.UUID | None
    created_at: str
    # Solde restant dû et statut de paiement (4C) : remplis uniquement pour une
    # facture émise ; None ailleurs (brouillon, devis, avoir, facture annulée).
    outstanding_ttc: int | None = None
    payment_status: PaymentStatusParam | None = None
    # Nombre de relances déjà envoyées (4D) : rempli uniquement pour une facture
    # émise dans les routes de lecture (calcul en lecture, jamais stocké).
    reminders_count: int | None = None
    # Écriture validée qui porte le document en comptabilité (4E) : NULL tant
    # que le comptable n'a pas comptabilisé — jamais automatique.
    entry_id: uuid.UUID | None = None


class DocumentDetailOut(DocumentOut):
    lines: list[LineOut]
    partner_snapshot: dict[str, Any] | None
    issuer_snapshot: dict[str, Any] | None


class DocumentsOut(BaseModel):
    items: list[DocumentOut]
    total: int


class DocumentIssuedOut(BaseModel):
    """Résultat d'une numérotation définitive : document émis et mentions légales
    manquantes signalées (non bloquant en 4B, règle dure avec le PDF en 4B-bis)."""

    document: DocumentDetailOut
    warnings: list[str]


class DocumentCreate(RequestBody):
    doc_kind: DocKindParam
    partner_id: uuid.UUID
    lines: Annotated[list[LineIn], Field(min_length=1, max_length=50)]
    due_on: date | None = None
    valid_until: date | None = None
    notes: str | None = None
    origin_document_id: uuid.UUID | None = None
    reverses_document_id: uuid.UUID | None = None


class DocumentUpdate(RequestBody):
    """PATCH partiel d'un brouillon : seuls les champs fournis sont modifiés ;
    « lines » remplace intégralement les lignes."""

    due_on: date | None = None
    valid_until: date | None = None
    notes: str | None = None
    lines: Annotated[list[LineIn] | None, Field(min_length=1, max_length=50)] = None

    @model_validator(mode="after")
    def _not_empty(self) -> "DocumentUpdate":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self


class IssueIn(RequestBody):
    """Émission avec date explicite facultative (rattrapage de saisie) : la date
    doit tomber dans un exercice ouvert, hors période verrouillée."""

    issued_on: date | None = None


class DecisionIn(RequestBody):
    accepted: bool


class DocumentEntryIn(RequestBody):
    """Comptabilisation d'un document émis : le compte de produits est choisi par
    le comptable (défaut : numéro 701 du plan du dossier) ; la TVA suit les
    comptes collectés des taux figés à l'émission."""

    sales_account_id: uuid.UUID | None = None


class PaymentEntryIn(RequestBody):
    """Comptabilisation d'un règlement : le compte de trésorerie est choisi par
    le comptable (défaut : 571 pour la caisse, 521 pour les autres modes)."""

    cash_account_id: uuid.UUID | None = None


def _data(body: DocumentCreate) -> DocumentData:
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
        valid_until=body.valid_until,
        notes=body.notes,
        origin_document_id=body.origin_document_id,
        reverses_document_id=body.reverses_document_id,
    )


def _line_out(line: SalesDocumentLine) -> LineOut:
    return LineOut(
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
    document: SalesDocument,
    lettres: dict[uuid.UUID, int] | None = None,
    relances: dict[uuid.UUID, int] | None = None,
) -> DocumentOut:
    outstanding: int | None = None
    payment_status: payments.PaymentStatus | None = None
    nombre_relances: int | None = None
    if document.doc_kind == "invoice" and document.status == "ISSUED":
        credited = (lettres or {}).get(document.id, 0)
        outstanding = document.total_ttc - credited
        payment_status = payments.payment_status_for(outstanding, document.total_ttc)
        nombre_relances = (relances or {}).get(document.id, 0)
    return DocumentOut(
        id=document.id,
        doc_kind=document.doc_kind,
        status=document.status,
        number=document.number,
        issued_on=document.issued_on.isoformat() if document.issued_on else None,
        due_on=document.due_on.isoformat() if document.due_on else None,
        valid_until=document.valid_until.isoformat() if document.valid_until else None,
        partner_id=document.partner_id,
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
        reminders_count=nombre_relances,
        entry_id=document.entry_id,
    )


def _detail_out(
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    lettres: dict[uuid.UUID, int] | None = None,
    relances: dict[uuid.UUID, int] | None = None,
) -> DocumentDetailOut:
    return DocumentDetailOut(
        **_out(document, lettres, relances).model_dump(),
        lines=[_line_out(line) for line in lines],
        partner_snapshot=document.partner_snapshot,
        issuer_snapshot=document.issuer_snapshot,
    )


def _lettres(db: DbSession, company_id: uuid.UUID, document: SalesDocument) -> dict[uuid.UUID, int]:
    """Sommes lettrées d'un document unique (détail et mutations) : une requête."""
    return payments.outstanding_for_documents(db, company_id, [document.id])


@router.get("/sales", responses={404: {"model": ErrorResponse}})
def list_documents(
    tenant: SalesRead,
    db: DbSession,
    kind: DocKindParam | None = None,
    status_filter: Annotated[DocStatusParam | None, Query(alias="status")] = None,
    partner_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> DocumentsOut:
    """Devis, factures et avoirs du dossier, filtrables et paginés."""
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
    relances = reminders.reminders_count_for_documents(db, tenant.company_id, [d.id for d in items])
    return DocumentsOut(items=[_out(d, lettres, relances) for d in items], total=total)


@router.post("/sales", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_document(
    body: DocumentCreate, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    created = service.create_document(db, _actor(tenant, ctx), _data(body))
    document, lines = service.get_document(db, tenant.company_id, created.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.get("/sales/{document_id}", responses={404: {"model": ErrorResponse}})
def get_document(document_id: uuid.UUID, tenant: SalesRead, db: DbSession) -> DocumentDetailOut:
    document, lines = service.get_document(db, tenant.company_id, document_id)
    return _detail_out(
        document,
        lines,
        _lettres(db, tenant.company_id, document),
        reminders.reminders_count_for_documents(db, tenant.company_id, [document.id]),
    )


@router.patch("/sales/{document_id}", responses=WRITE_ERRORS)
def update_document(
    document_id: uuid.UUID,
    body: DocumentUpdate,
    tenant: SalesManage,
    db: DbSession,
    ctx: Ctx,
) -> DocumentDetailOut:
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


@router.delete("/sales/{document_id}", status_code=204, responses=WRITE_ERRORS)
def delete_document(document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx) -> None:
    service.delete_draft(db, _actor(tenant, ctx), document_id)


@router.post("/sales/{document_id}/issue", responses=WRITE_ERRORS)
def issue_document(
    document_id: uuid.UUID,
    tenant: SalesManage,
    db: DbSession,
    ctx: Ctx,
    body: IssueIn | None = None,
) -> DocumentIssuedOut:
    """Numérotation définitive d'une facture ou d'un avoir : irréversible, sans trou."""
    issued_on = body.issued_on if body is not None else None
    document, warnings = service.issue_document(
        db, _actor(tenant, ctx), document_id, issued_on=issued_on
    )
    _, lines = service.get_document(db, tenant.company_id, document.id)
    return DocumentIssuedOut(
        document=_detail_out(document, lines, _lettres(db, tenant.company_id, document)),
        warnings=warnings,
    )


@router.post("/sales/{document_id}/send", responses=WRITE_ERRORS)
def send_quote(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentIssuedOut:
    """Envoi d'un devis : numérotation définitive (chronologie sans trou)."""
    document, warnings = service.send_quote(db, _actor(tenant, ctx), document_id)
    _, lines = service.get_document(db, tenant.company_id, document.id)
    return DocumentIssuedOut(
        document=_detail_out(document, lines, _lettres(db, tenant.company_id, document)),
        warnings=warnings,
    )


@router.post("/sales/{document_id}/decision", responses=WRITE_ERRORS)
def decide_quote(
    document_id: uuid.UUID,
    body: DecisionIn,
    tenant: SalesManage,
    db: DbSession,
    ctx: Ctx,
) -> DocumentDetailOut:
    decided = service.decide_quote(db, _actor(tenant, ctx), document_id, body.accepted)
    document, lines = service.get_document(db, tenant.company_id, decided.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.post(
    "/sales/{document_id}/convert", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS
)
def convert_quote(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    """Convertit un devis accepté en facture brouillon (numérotée à son émission)."""
    created = service.convert_quote(db, _actor(tenant, ctx), document_id)
    document, lines = service.get_document(db, tenant.company_id, created.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


@router.post("/sales/{document_id}/cancel", responses=WRITE_ERRORS)
def cancel_invoice(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    """Annulation d'une facture émise sans avoir : le numéro est conservé."""
    cancelled = service.cancel_invoice(db, _actor(tenant, ctx), document_id)
    document, lines = service.get_document(db, tenant.company_id, cancelled.id)
    return _detail_out(document, lines, _lettres(db, tenant.company_id, document))


_PDF_FILE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        "description": "PDF conforme du document de vente",
    },
    **TENANT_ERRORS,
    422: {"model": ErrorResponse},  # brouillon jamais numéroté : pas de PDF
    # KF-13 : quota d'exports (compteurs partagés avec les exports comptables).
    429: {"model": ErrorResponse},
}


@router.get("/sales/{document_id}/pdf", response_class=Response, responses=_PDF_FILE)
def export_document_pdf(
    document_id: uuid.UUID, tenant: SalesRead, db: DbSession, ctx: Ctx
) -> Response:
    """PDF conforme du document numéroté (facture, devis envoyé, avoir) : mentions
    légales figées à la numérotation, montants et exercice. Un brouillon est refusé."""
    exported = service.export_document_pdf(db, tenant.company_id, document_id, _actor(tenant, ctx))
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{exported.filename}"; '
                f"filename*=UTF-8''{quote(exported.filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


# --- Règlements clients et lettrage commercial (Phase 4C) ---------------------


class AllocationIn(BaseModel):
    document_id: uuid.UUID
    amount: Annotated[int, Field(gt=0)]


class PaymentIn(RequestBody):
    """Règlement saisi : les affectations sont facultatives (lot B-3) — sans
    facture visée, `amount` est obligatoire (acompte reçu du tier client
    `partner_id`) ; avec affectations, `amount` (facultatif) doit être au moins
    égal à leur somme — l'excédent est un trop-perçu non lettré. Le service
    contrôle chaque affectation sous verrou de la facture."""

    paid_on: date
    method: PaymentMethodParam
    allocations: Annotated[list[AllocationIn], Field(default=[], max_length=50)]
    reference: Annotated[str | None, Field(max_length=100)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    amount: Annotated[int | None, Field(gt=0)] = None
    partner_id: uuid.UUID | None = None


class RefundIn(RequestBody):
    """Remboursement saisi (lot B-3) : une part du reste non affecté d'un
    règlement rendue au client — jamais au-delà du disponible contrôlé sous
    verrou (montant - affectations - remboursements déjà saisis)."""

    refunded_on: date
    method: PaymentMethodParam
    amount: Annotated[int, Field(gt=0)]
    reference: Annotated[str | None, Field(max_length=100)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None


class AllocationTargetsIn(RequestBody):
    """Affectation ultérieure (lot B-3) : montants cibles **absolus** par
    facture — répéter la même demande ne change rien (idempotence), seule la
    hausse est permise et la somme cible ne dépasse jamais le disponible."""

    allocations: Annotated[list[AllocationIn], Field(min_length=1, max_length=50)]


class AllocationOut(BaseModel):
    document_id: uuid.UUID
    amount: int
    # Écriture qui couvre cette affectation (règlement posté ou transfert
    # d'acompte) : NULL tant que non couverte (lot B-3).
    entry_id: uuid.UUID | None = None


class RefundOut(BaseModel):
    """Remboursement d'une part du reste non affecté (lot B-3)."""

    id: uuid.UUID
    payment_id: uuid.UUID
    refunded_on: str
    method: PaymentMethodParam
    reference: str | None
    notes: str | None
    amount: int
    currency: str
    entry_id: uuid.UUID | None = None
    created_at: str


class PaymentOut(BaseModel):
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
    allocations: list[AllocationOut]
    # Reste non affecté (acompte ou trop-perçu) : montant - affectations -
    # remboursements, calculé en lecture (lot B-3).
    unallocated: int
    refunds: list[RefundOut]
    # Écriture validée qui porte l'encaissement en comptabilité (4E).
    entry_id: uuid.UUID | None = None


class PaymentsOut(BaseModel):
    items: list[PaymentOut]
    total: int


class AgingBucketOut(BaseModel):
    count: int
    total_ttc: int


class AgingOut(BaseModel):
    """Balance âgée clients : créances émises non soldées par ancienneté de retard."""

    as_of: str
    buckets: dict[str, AgingBucketOut]
    grand_total_ttc: int


def _payment_data(body: PaymentIn) -> payments.PaymentData:
    return payments.PaymentData(
        paid_on=body.paid_on,
        method=body.method,
        allocations=tuple(
            payments.AllocationData(document_id=a.document_id, amount=a.amount)
            for a in body.allocations
        ),
        reference=body.reference,
        notes=body.notes,
        amount=body.amount,
        partner_id=body.partner_id,
    )


def _payment_out(
    payment: SalesPayment,
    allocations: list[SalesPaymentAllocation],
    refunds: list[SalesRefund] | None = None,
) -> PaymentOut:
    rembourses = refunds if refunds is not None else []
    return PaymentOut(
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
            AllocationOut(document_id=a.document_id, amount=a.amount, entry_id=a.entry_id)
            for a in allocations
        ],
        unallocated=payments.unallocated_of(payment, allocations, rembourses),
        refunds=[_refund_out(r) for r in rembourses],
        entry_id=payment.entry_id,
    )


def _refund_out(refund: SalesRefund) -> RefundOut:
    return RefundOut(
        id=refund.id,
        payment_id=refund.payment_id,
        refunded_on=refund.refunded_on.isoformat(),
        method=refund.method,
        reference=refund.reference,
        notes=refund.notes,
        amount=refund.amount,
        currency=refund.currency,
        entry_id=refund.entry_id,
        created_at=refund.created_at.isoformat(),
    )


@router.get("/payments", responses={404: {"model": ErrorResponse}})
def list_payments(
    tenant: SalesRead,
    db: DbSession,
    partner_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PaymentsOut:
    """Règlements du dossier (encaissements lettrés), filtrables et paginés."""
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
    par_rembourse = payments.refunds_of_payments(db, tenant.company_id, [p.id for p in items])
    return PaymentsOut(
        items=[
            _payment_out(
                p,
                par_reglement.get(p.id, []),
                par_rembourse.get(p.id, []),
            )
            for p in items
        ],
        total=total,
    )


@router.post("/payments", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_payment(body: PaymentIn, tenant: SalesManage, db: DbSession, ctx: Ctx) -> PaymentOut:
    """Enregistre un règlement client et son lettrage : le solde des factures
    visées est contrôlé sous verrou — jamais d'affectation au-delà du restant dû."""
    created = payments.create_payment(db, _actor(tenant, ctx), _payment_data(body))
    payment, allocations = payments.get_payment(db, tenant.company_id, created.id)
    return _payment_out(payment, allocations)


@router.get("/payments/{payment_id}", responses={404: {"model": ErrorResponse}})
def get_payment(payment_id: uuid.UUID, tenant: SalesRead, db: DbSession) -> PaymentOut:
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    rembourses = payments.refunds_of_payments(db, tenant.company_id, [payment_id]).get(
        payment_id, []
    )
    return _payment_out(payment, allocations, rembourses)


@router.delete("/payments/{payment_id}", status_code=204, responses=WRITE_ERRORS)
def delete_payment(payment_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx) -> None:
    """Supprime un règlement (correction de saisie) : les soldes des factures
    sont libérés et l'action est journalisée. Refusé tant que le règlement est
    comptabilisé : l'écriture se contre-passe d'abord au grand livre."""
    payments.delete_payment(db, _actor(tenant, ctx), payment_id)


@router.post("/sales/{document_id}/entry", responses=WRITE_ERRORS)
def post_document_entry(
    document_id: uuid.UUID,
    body: DocumentEntryIn,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> DocumentDetailOut:
    """Comptabilise une facture ou un avoir émis : écriture validée du journal des
    ventes (débit 411x au TTC, crédit du compte de produits au HT, crédit des
    comptes collectés par taux — inversée pour un avoir), liée au document.
    Idempotence refusée : un document déjà comptabilisé répond 409."""
    accounting.post_document(
        db,
        _actor(tenant, ctx),
        document_id,
        sales_account_id=body.sales_account_id,
    )
    document, lines = service.get_document(db, tenant.company_id, document_id)
    return _detail_out(
        document,
        lines,
        _lettres(db, tenant.company_id, document),
        reminders.reminders_count_for_documents(db, tenant.company_id, [document.id]),
    )


@router.post("/payments/{payment_id}/entry", responses=WRITE_ERRORS)
def post_payment_entry(
    payment_id: uuid.UUID,
    body: PaymentEntryIn,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> PaymentOut:
    """Comptabilise un règlement : écriture validée du journal de trésorerie
    (débit du compte de trésorerie, crédit du compte de tiers pour la part
    affectée et du 4191 pour le reste non affecté — acompte ou trop-perçu),
    liée au règlement. Idempotence refusée : un règlement déjà comptabilisé
    répond 409."""
    accounting.post_payment(
        db,
        _actor(tenant, ctx),
        payment_id,
        cash_account_id=body.cash_account_id,
    )
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    rembourses = payments.refunds_of_payments(db, tenant.company_id, [payment_id]).get(
        payment_id, []
    )
    return _payment_out(payment, allocations, rembourses)


@router.post("/payments/{payment_id}/allocations", responses=WRITE_ERRORS)
def allocate_payment(
    payment_id: uuid.UUID,
    body: AllocationTargetsIn,
    tenant: SalesManage,
    db: DbSession,
    ctx: Ctx,
) -> PaymentOut:
    """**Affectation ultérieure** (lot B-3) : affecte le reste non affecté d'un
    règlement (acompte ou trop-perçu) à des factures émises du même tier.
    Cibles absolues et idempotentes : répéter la même demande ne change rien ;
    hausse seule permise ; la somme cible ne dépasse jamais le disponible
    (montant - remboursements) ni les soldes des factures (contrôles sous
    verrou)."""
    payments.allocate_payment(
        db,
        _actor(tenant, ctx),
        payment_id,
        tuple(
            payments.AllocationData(document_id=a.document_id, amount=a.amount)
            for a in body.allocations
        ),
    )
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    rembourses = payments.refunds_of_payments(db, tenant.company_id, [payment_id]).get(
        payment_id, []
    )
    return _payment_out(payment, allocations, rembourses)


@router.post(
    "/payments/{payment_id}/refund", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS
)
def create_payment_refund(
    payment_id: uuid.UUID, body: RefundIn, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> RefundOut:
    """**Remboursement** (lot B-3) : rend au client une part du reste non affecté
    du règlement — jamais au-delà du disponible contrôlé sous verrou. Aucune
    écriture n'est générée : la comptabilisation (débit 4191, crédit
    trésorerie) reste explicite (`entries:post`)."""
    refund = payments.refund_payment(
        db,
        _actor(tenant, ctx),
        payment_id,
        payments.RefundData(
            refunded_on=body.refunded_on,
            method=body.method,
            amount=body.amount,
            reference=body.reference,
            notes=body.notes,
        ),
    )
    return _refund_out(refund)


@router.delete("/payment-refunds/{refund_id}", status_code=204, responses=WRITE_ERRORS)
def delete_payment_refund(
    refund_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> None:
    """Supprime un remboursement (correction de saisie) : le disponible du
    règlement porteur est restitué, l'action est journalisée. Refusé tant que
    le remboursement est comptabilisé : l'écriture se contre-passe d'abord."""
    payments.delete_refund(db, _actor(tenant, ctx), refund_id)


@router.post("/payments/{payment_id}/allocation-entry", responses=WRITE_ERRORS)
def post_allocation_entry(
    payment_id: uuid.UUID,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> PaymentOut:
    """Transfert d'acompte (lot B-3) : couvre en comptabilité les affectations
    ajoutées après la comptabilisation du règlement — débit du 4191 « Clients,
    avances et acomptes reçus », crédit du compte de tiers, au journal des
    opérations diverses. Idempotence refusée : rien à transférer répond 409."""
    accounting.post_allocation_entry(db, _actor(tenant, ctx), payment_id)
    payment, allocations = payments.get_payment(db, tenant.company_id, payment_id)
    rembourses = payments.refunds_of_payments(db, tenant.company_id, [payment_id]).get(
        payment_id, []
    )
    return _payment_out(payment, allocations, rembourses)


@router.post("/payment-refunds/{refund_id}/entry", responses=WRITE_ERRORS)
def post_refund_entry(
    refund_id: uuid.UUID,
    body: PaymentEntryIn,
    tenant: EntriesPost,
    db: DbSession,
    ctx: Ctx,
) -> RefundOut:
    """Comptabilise un remboursement (lot B-3) : écriture validée du journal de
    trésorerie — débit du 4191 « Clients, avances et acomptes reçus », crédit du
    compte de trésorerie. Exige un règlement porteur comptabilisé (écriture
    vivante) ; idempotence refusée (409)."""
    accounting.post_refund_entry(
        db, _actor(tenant, ctx), refund_id, cash_account_id=body.cash_account_id
    )
    return _refund_out(payments.get_refund(db, tenant.company_id, refund_id))


@router.get("/receivables/aging", responses={404: {"model": ErrorResponse}})
def receivables_aging(
    tenant: SalesRead,
    db: DbSession,
    as_of: date | None = None,
) -> AgingOut:
    """Balance âgée clients : factures émises non soldées, par ancienneté de
    retard au jour demandé (aujourd'hui par défaut)."""
    body = payments.receivables_aging(db, tenant.company_id, as_of or utcnow().date())
    return AgingOut(
        as_of=body.as_of.isoformat(),
        buckets={
            cle: AgingBucketOut(count=b.count, total_ttc=b.total_ttc)
            for cle, b in body.buckets.items()
        },
        grand_total_ttc=body.grand_total_ttc,
    )


# --- Relances de factures échues (Phase 4D) -----------------------------------


class ReminderIn(RequestBody):
    """Relance demandée : la facture visée et la date du rappel. Le niveau est
    compté par le service (jamais saisi) ; une même facture ne reçoit qu'une
    relance par jour (unicité en base — doublon refusé 409)."""

    document_id: uuid.UUID
    reminded_on: date
    note: Annotated[str | None, Field(max_length=2000)] = None


class ReminderOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    partner_id: uuid.UUID
    level: int
    reminded_on: str
    channel: Literal["EMAIL"]
    email_to: str
    note: str | None
    created_at: str


class ReminderCreatedOut(BaseModel):
    """Résultat d'une relance enregistrée : `email_queued` est False si la file
    d'attente était injoignable — la relance reste enregistrée et renvoyable."""

    reminder: ReminderOut
    email_queued: bool


class RemindersOut(BaseModel):
    items: list[ReminderOut]
    total: int


class ResendOut(BaseModel):
    email_queued: bool


class OverdueItemOut(BaseModel):
    """Une facture échue candidate à la relance, avec son historique."""

    document_id: uuid.UUID
    number: int
    partner_id: uuid.UUID
    partner_name: str
    partner_email: str | None
    currency: str
    total_ttc: int
    outstanding_ttc: int
    due_on: str
    days_late: int
    reminders_count: int
    next_level: int


class OverdueOut(BaseModel):
    as_of: str
    items: list[OverdueItemOut]


def _reminder_out(reminder: SalesReminder) -> ReminderOut:
    return ReminderOut(
        id=reminder.id,
        document_id=reminder.document_id,
        partner_id=reminder.partner_id,
        level=reminder.level,
        reminded_on=reminder.reminded_on.isoformat(),
        channel="EMAIL",
        email_to=reminder.email_to,
        note=reminder.note,
        created_at=reminder.created_at.isoformat(),
    )


@router.get("/receivables/overdue", responses={404: {"model": ErrorResponse}})
def receivables_overdue(
    tenant: SalesRead,
    db: DbSession,
    as_of: date | None = None,
) -> OverdueOut:
    """Factures échues non soldées, candidates à la relance : retard en jours,
    historique de relances et adresse email du tier (absente : la fiche du tier
    doit être complétée avant toute relance)."""
    items = reminders.overdue_invoices(db, tenant.company_id, as_of or utcnow().date())
    return OverdueOut(
        as_of=(as_of or utcnow().date()).isoformat(),
        items=[
            OverdueItemOut(
                document_id=c.document.id,
                number=c.document.number or 0,
                partner_id=c.document.partner_id,
                partner_name=c.partner_name,
                partner_email=c.partner_email,
                currency=c.document.currency,
                total_ttc=c.document.total_ttc,
                outstanding_ttc=c.outstanding_ttc,
                due_on=(
                    c.document.due_on or c.document.issued_on or c.document.created_at.date()
                ).isoformat(),
                days_late=c.days_late,
                reminders_count=c.reminders_count,
                next_level=c.next_level,
            )
            for c in items
        ],
    )


@router.get("/reminders", responses={404: {"model": ErrorResponse}})
def list_reminders(
    tenant: SalesRead,
    db: DbSession,
    document_id: uuid.UUID | None = None,
    partner_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> RemindersOut:
    """Relances du dossier (historique immuable), filtrables et paginées."""
    items, total = reminders.list_reminders(
        db,
        tenant.company_id,
        document_id=document_id,
        partner_id=partner_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return RemindersOut(items=[_reminder_out(r) for r in items], total=total)


@router.post("/reminders", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_reminder(
    body: ReminderIn, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> ReminderCreatedOut:
    """Enregistre une relance d'une facture échue et programme l'email de
    rappel. Le niveau est compté sous verrou de la facture ; une panne de la
    file n'annule pas l'enregistrement (`email_queued` False : la relance reste
    renvoyable). Aucune écriture comptable."""
    created = reminders.create_reminder(
        db,
        _actor(tenant, ctx),
        reminders.ReminderData(
            document_id=body.document_id,
            reminded_on=body.reminded_on,
            note=body.note,
        ),
    )
    queued = enqueue_best_effort(send_sales_reminder, str(tenant.company_id), str(created.id))
    return ReminderCreatedOut(reminder=_reminder_out(created), email_queued=queued)


@router.post("/reminders/{reminder_id}/resend", responses=WRITE_ERRORS)
def resend_reminder(
    reminder_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> ResendOut:
    """Re-programme l'envoi email d'une relance déjà enregistrée (après une
    file injoignable) : journalisé, la relance reste inchangée."""
    reminders.resend_reminder(db, _actor(tenant, ctx), reminder_id)
    queued = enqueue_best_effort(send_sales_reminder, str(tenant.company_id), str(reminder_id))
    return ResendOut(email_queued=queued)


# --- Relances automatiques configurables (Phase B, lot 2) ----------------------


class ReminderPolicyOut(BaseModel):
    """Politique effective de relance automatique du dossier : valeurs par
    défaut d'affichage si jamais paramétrée (jamais appliquées sans
    enregistrement explicite — `enabled` False tant que la politique n'existe
    pas)."""

    enabled: bool
    offsets_days: list[int]
    updated_at: str | None


class ReminderPolicyIn(BaseModel):
    """Réglage demandé : activation et échéancier d'escalade — 1 à 6 seuils,
    entiers de 1 à 365 jours de retard, strictement croissants (chaque seuil
    déclenche le niveau de relance suivant)."""

    enabled: bool
    offsets_days: Annotated[list[int], Field(max_length=6)]


def _policy_out(policy: SalesReminderPolicy | None) -> ReminderPolicyOut:
    if policy is None:
        return ReminderPolicyOut(
            enabled=False,
            offsets_days=list(auto_reminders.DEFAULT_OFFSETS_DAYS),
            updated_at=None,
        )
    return ReminderPolicyOut(
        enabled=policy.enabled,
        offsets_days=[int(v) for v in policy.offsets_days],
        updated_at=policy.updated_at.isoformat(),
    )


@router.get("/reminders/policy", responses={404: {"model": ErrorResponse}})
def get_reminder_policy(tenant: SalesRead, db: DbSession) -> ReminderPolicyOut:
    """Politique de relance automatique du dossier (défauts d'affichage si
    jamais paramétrée : relances automatiques désactivées)."""
    return _policy_out(auto_reminders.get_policy(db, tenant.company_id))


@router.put("/reminders/policy", responses=WRITE_ERRORS)
def put_reminder_policy(
    body: ReminderPolicyIn, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> ReminderPolicyOut:
    """Crée ou met à jour la politique de relance automatique du dossier
    (upsert, audité). L'exécution est périodique (planificateur → worker) :
    une relance par facture et par jour, même unicité que la relance manuelle
    (4D) — aucun doublon, aucune écriture comptable."""
    policy = auto_reminders.upsert_policy(
        db,
        _actor(tenant, ctx),
        auto_reminders.PolicyData(enabled=body.enabled, offsets_days=body.offsets_days),
    )
    return _policy_out(policy)


# --- Envoi d'un document de vente par email avec son PDF (4D-bis) ------------


class DocumentEmailIn(BaseModel):
    """Envoi demandé : destinataire explicite facultatif (sinon l'email de la
    fiche du tier) et message personnalisé facultatif."""

    to: EmailStr | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None


class DocumentEmailOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    partner_id: uuid.UUID
    email_to: str
    note: str | None
    created_at: str


class DocumentEmailCreatedOut(BaseModel):
    """Résultat d'un envoi enregistré : `email_queued` est False si la file
    d'attente était injoignable — l'envoi reste enregistré et renvoyable."""

    email: DocumentEmailOut
    email_queued: bool


class DocumentEmailsOut(BaseModel):
    items: list[DocumentEmailOut]
    total: int


def _document_email_out(envoi: SalesDocumentEmail) -> DocumentEmailOut:
    return DocumentEmailOut(
        id=envoi.id,
        document_id=envoi.document_id,
        partner_id=envoi.partner_id,
        email_to=envoi.email_to,
        note=envoi.note,
        created_at=envoi.created_at.isoformat(),
    )


@router.get("/sales/{document_id}/emails", responses={404: {"model": ErrorResponse}})
def list_document_emails(
    document_id: uuid.UUID, tenant: SalesRead, db: DbSession
) -> DocumentEmailsOut:
    """Historique immuable des envois email d'un document (du plus récent au
    plus ancien)."""
    items, total = document_emails.list_emails(db, tenant.company_id, document_id)
    return DocumentEmailsOut(items=[_document_email_out(e) for e in items], total=total)


@router.post(
    "/sales/{document_id}/email",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
def send_document_email(
    document_id: uuid.UUID, body: DocumentEmailIn, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentEmailCreatedOut:
    """Enregistre l'envoi d'un document numéroté par email et programme la
    livraison du PDF en pièce jointe dans le worker. Le PDF est rendu depuis les
    instantanés figés à l'émission ; une facture annulée ne part pas. Une panne
    de la file n'annule pas l'enregistrement (`email_queued` False : l'envoi
    reste renvoyable). Aucune écriture comptable."""
    envoi = document_emails.create_email_send(
        db,
        _actor(tenant, ctx),
        document_emails.DocumentEmailData(document_id=document_id, to=body.to, note=body.note),
    )
    queued = enqueue_best_effort(send_sales_document_email, str(tenant.company_id), str(envoi.id))
    return DocumentEmailCreatedOut(email=_document_email_out(envoi), email_queued=queued)


# --- Échéanciers clients et indicateurs de recouvrement (lot B-4) -------------


# Réponse binaire de l'export balance âgée : mêmes types de fichiers que les
# exports comptables (PDF et Excel), même quota KF-13 côté service.
_AGING_FILE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {
            media: {"schema": {"type": "string", "format": "binary"}}
            for media in (
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        "description": "Fichier exporté",
    },
    **TENANT_ERRORS,
    422: TENANT_ERRORS[404],
    429: {"model": ErrorResponse},
}

AgingFileFormat = Annotated[
    Literal["pdf", "xlsx"], Query(alias="format", description="pdf ou xlsx")
]


class ScheduleLineBody(RequestBody):
    """Une tranche du plan : date attendue, montant attendu (unités mineures,
    strictement positif), note facultative."""

    expected_on: date
    expected_amount: Annotated[int, Field(gt=0)]
    note: Annotated[str | None, Field(max_length=500)] = None


class SchedulePutIn(RequestBody):
    """Le plan complet d'une facture : remplacé en bloc (sémantique PUT), les
    tranches renumérotées 1..N. Répéter le même plan = même état (idempotent)."""

    lines: Annotated[list[ScheduleLineBody], Field(min_length=1, max_length=24)]


class ScheduleLineOut(BaseModel):
    line_no: int
    expected_on: str
    expected_amount: int
    note: str | None
    status: Literal["settled", "late", "upcoming"]


class ScheduleOut(BaseModel):
    document_id: uuid.UUID
    document_number: int | None
    currency: str
    total_ttc: int
    paid_ttc: int
    outstanding_ttc: int
    planned_total: int
    planned_remaining: int
    lines: list[ScheduleLineOut]


class TopDebtorOut(BaseModel):
    partner_id: uuid.UUID
    partner_name: str
    outstanding_ttc: int
    max_days_late: int


class KpisOut(BaseModel):
    """Indicateurs de recouvrement au jour demandé : encours, part échue, DSO
    en jours de ventes, taux de recouvrement et top débiteurs. Tout est calculé
    en lecture depuis les mêmes soldes que la balance âgée 4C."""

    as_of: str
    lookback_days: int
    outstanding_ttc: int
    overdue_ttc: int
    overdue_share_bp: int
    weighted_days_late: int
    dso_days: int
    billed_ttc: int
    collected_ttc: int
    recovery_rate_bp: int
    top_debtors: list[TopDebtorOut]


def _schedule_out(view: schedules.ScheduleView) -> ScheduleOut:
    return ScheduleOut(
        document_id=view.document_id,
        document_number=view.document_number,
        currency=view.currency,
        total_ttc=view.total_ttc,
        paid_ttc=view.paid_ttc,
        outstanding_ttc=view.outstanding_ttc,
        planned_total=view.planned_total,
        planned_remaining=view.planned_remaining,
        lines=[
            ScheduleLineOut(
                line_no=line.line_no,
                expected_on=line.expected_on.isoformat(),
                expected_amount=line.expected_amount,
                note=line.note,
                status=line.status,
            )
            for line in view.lines
        ],
    )


@router.get("/sales/{document_id}/schedule", responses={404: {"model": ErrorResponse}})
def get_schedule(document_id: uuid.UUID, tenant: SalesRead, db: DbSession) -> ScheduleOut:
    """L'échéancier d'une facture, statué au jour présent : chaque tranche est
    réglée (cumul encaissé atteint), en retard (date passée) ou à venir. La
    lecture n'écrit rien et n'écrit jamais en comptabilité."""
    return _schedule_out(schedules.get_schedule(db, tenant.company_id, document_id))


@router.put("/sales/{document_id}/schedule", responses=WRITE_ERRORS)
def replace_schedule(
    document_id: uuid.UUID, body: SchedulePutIn, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> ScheduleOut:
    """Remplace le plan d'une facture émise en bloc (PUT idempotent). Refusé
    pour un brouillon, un devis, un avoir ou une facture annulée ; la somme des
    tranches ne peut pas dépasser le solde restant dû (contrôlé sous verrou du
    document, sérialisé avec les règlements). Journalisé ; aucune écriture
    comptable."""
    view = schedules.replace_schedule(
        db,
        _actor(tenant, ctx),
        document_id,
        [
            schedules.ScheduleLineIn(
                expected_on=line.expected_on,
                expected_amount=line.expected_amount,
                note=line.note,
            )
            for line in body.lines
        ],
    )
    return _schedule_out(view)


class ScheduleSummaryOut(BaseModel):
    document_id: uuid.UUID
    document_number: int
    partner_id: uuid.UUID
    partner_name: str
    currency: str
    total_ttc: int
    paid_ttc: int
    outstanding_ttc: int
    planned_total: int
    planned_remaining: int
    lines: list[ScheduleLineOut]


class SchedulesOut(BaseModel):
    as_of: str
    items: list[ScheduleSummaryOut]


@router.get("/receivables/schedules", responses={404: {"model": ErrorResponse}})
def list_schedules(tenant: SalesRead, db: DbSession, as_of: date | None = None) -> SchedulesOut:
    """Tous les échéanciers du dossier, statués au jour demandé (aujourd'hui par
    défaut) : le plan de chaque facture émise qui en porte un, avec son contexte."""
    body = schedules.list_schedules(db, tenant.company_id, as_of or utcnow().date())
    return SchedulesOut(
        as_of=(as_of or utcnow().date()).isoformat(),
        items=[
            ScheduleSummaryOut(
                document_id=s.document_id,
                document_number=s.document_number,
                partner_id=s.partner_id,
                partner_name=s.partner_name,
                currency=s.currency,
                total_ttc=s.total_ttc,
                paid_ttc=s.paid_ttc,
                outstanding_ttc=s.outstanding_ttc,
                planned_total=s.planned_total,
                planned_remaining=s.planned_remaining,
                lines=[
                    ScheduleLineOut(
                        line_no=line.line_no,
                        expected_on=line.expected_on.isoformat(),
                        expected_amount=line.expected_amount,
                        note=line.note,
                        status=line.status,
                    )
                    for line in s.lines
                ],
            )
            for s in body
        ],
    )


@router.get("/receivables/kpis", responses={404: {"model": ErrorResponse}})
def receivables_kpis(
    tenant: SalesRead,
    db: DbSession,
    as_of: date | None = None,
    lookback_days: Annotated[int | None, Query(ge=7, le=365)] = None,
) -> KpisOut:
    """Indicateurs de recouvrement au jour demandé (aujourd'hui par défaut),
    fenêtre de mesure de 7 à 365 jours (90 par défaut)."""
    body = collections.receivables_kpis(
        db,
        tenant.company_id,
        as_of or utcnow().date(),
        lookback_days if lookback_days is not None else collections.DEFAULT_LOOKBACK_DAYS,
    )
    return KpisOut(
        as_of=body.as_of.isoformat(),
        lookback_days=body.lookback_days,
        outstanding_ttc=body.outstanding_ttc,
        overdue_ttc=body.overdue_ttc,
        overdue_share_bp=body.overdue_share_bp,
        weighted_days_late=body.weighted_days_late,
        dso_days=body.dso_days,
        billed_ttc=body.billed_ttc,
        collected_ttc=body.collected_ttc,
        recovery_rate_bp=body.recovery_rate_bp,
        top_debtors=[
            TopDebtorOut(
                partner_id=d.partner_id,
                partner_name=d.partner_name,
                outstanding_ttc=d.outstanding_ttc,
                max_days_late=d.max_days_late,
            )
            for d in body.top_debtors
        ],
    )


@router.get("/receivables/aging/export", response_class=Response, responses=_AGING_FILE)
def export_receivables_aging(
    tenant: SalesRead,
    db: DbSession,
    ctx: Ctx,
    file_format: AgingFileFormat,
    as_of: date | None = None,
) -> Response:
    """Export PDF/Excel de la balance âgée clients au jour demandé (lot B-4) :
    une section par bucket, une ligne par facture non soldée — la même
    répartition que la route JSON, sous quota d'exports (KF-13) et journalisée."""
    exported = export_service.generate_aging(
        db,
        tenant.company_id,
        as_of or utcnow().date(),
        file_format=file_format,
        actor_user_id=tenant.user.id,
        ctx=ctx,
    )
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{exported.filename}"; '
                f"filename*=UTF-8''{quote(exported.filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )
