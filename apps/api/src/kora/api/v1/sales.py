"""Routes des devis, factures et avoirs : cycle de vie et numérotation sans trou (4B).

Le PDF conforme d'un document numéroté (4B-bis) est servi en fichier binaire avec
les mentions légales figées à la numérotation."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from kora.accounting.entries import Actor
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.core.errors import ErrorResponse
from kora.models.sales import SalesDocument, SalesDocumentLine
from kora.sales import service
from kora.sales.service import DocumentData, LineData
from kora.tenancy.deps import SalesManage, SalesRead, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["ventes"])

DocKindParam = Literal["quote", "invoice", "credit_note"]
DocStatusParam = Literal["DRAFT", "SENT", "ACCEPTED", "REJECTED", "ISSUED", "CANCELLED"]


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


def _out(document: SalesDocument) -> DocumentOut:
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
    )


def _detail_out(document: SalesDocument, lines: list[SalesDocumentLine]) -> DocumentDetailOut:
    return DocumentDetailOut(
        **_out(document).model_dump(),
        lines=[_line_out(line) for line in lines],
        partner_snapshot=document.partner_snapshot,
        issuer_snapshot=document.issuer_snapshot,
    )


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
    return DocumentsOut(items=[_out(d) for d in items], total=total)


@router.post("/sales", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_document(
    body: DocumentCreate, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    created = service.create_document(db, _actor(tenant, ctx), _data(body))
    document, lines = service.get_document(db, tenant.company_id, created.id)
    return _detail_out(document, lines)


@router.get("/sales/{document_id}", responses={404: {"model": ErrorResponse}})
def get_document(document_id: uuid.UUID, tenant: SalesRead, db: DbSession) -> DocumentDetailOut:
    document, lines = service.get_document(db, tenant.company_id, document_id)
    return _detail_out(document, lines)


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
    return _detail_out(document, lines)


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
    return DocumentIssuedOut(document=_detail_out(document, lines), warnings=warnings)


@router.post("/sales/{document_id}/send", responses=WRITE_ERRORS)
def send_quote(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentIssuedOut:
    """Envoi d'un devis : numérotation définitive (chronologie sans trou)."""
    document, warnings = service.send_quote(db, _actor(tenant, ctx), document_id)
    _, lines = service.get_document(db, tenant.company_id, document.id)
    return DocumentIssuedOut(document=_detail_out(document, lines), warnings=warnings)


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
    return _detail_out(document, lines)


@router.post(
    "/sales/{document_id}/convert", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS
)
def convert_quote(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    """Convertit un devis accepté en facture brouillon (numérotée à son émission)."""
    created = service.convert_quote(db, _actor(tenant, ctx), document_id)
    document, lines = service.get_document(db, tenant.company_id, created.id)
    return _detail_out(document, lines)


@router.post("/sales/{document_id}/cancel", responses=WRITE_ERRORS)
def cancel_invoice(
    document_id: uuid.UUID, tenant: SalesManage, db: DbSession, ctx: Ctx
) -> DocumentDetailOut:
    """Annulation d'une facture émise sans avoir : le numéro est conservé."""
    cancelled = service.cancel_invoice(db, _actor(tenant, ctx), document_id)
    document, lines = service.get_document(db, tenant.company_id, cancelled.id)
    return _detail_out(document, lines)


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
