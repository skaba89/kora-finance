"""Envoi des documents de vente par email avec PDF en pièce jointe (4D-bis).

Règles portées par le service (et la base quand possible) :
- un envoi vise un document numéroté : facture ou avoir ÉMIS, devis envoyé,
  accepté ou refusé — un brouillon n'a ni numéro ni PDF (4B-bis), une facture
  annulée n'a plus de valeur commerciale (timbre « ANNULÉE ») et ne part pas ;
- le destinataire est l'adresse explicite de la demande, sinon l'email de la
  fiche du tier ; sans l'un ni l'autre, l'envoi est refusé avec un message
  clair (comme en 4D : compléter la fiche avant d'écrire au client) ;
- l'envoi est enregistré et immuable, puis l'email part dans le worker (jamais
  pendant la requête) : une panne de la file n'annule pas l'enregistrement,
  `email_queued` est False et le renvoi est possible depuis l'historique ;
- contrairement à la relance (4D), un même document peut être renvoyé plusieurs
  fois le même jour (le client redemande l'exemplaire) : chaque envoi est
  enregistré et journalisé — pas d'unicité quotidienne ;
- le PDF joint est rendu dans le worker depuis les instantanés figés à
  l'émission (émetteur, tier, lignes, taux datés) — jamais depuis les fiches
  vivantes ; si le document est annulé entre la mise en file et le traitement,
  l'envoi est abandonné sans réessai (renvoyer une facture annulée serait
  trompeur) ;
- aucune écriture comptable n'est générée ici (garde-fou maintenu depuis 4A) :
  l'envoi est un acte commercial documenté, pas un fait financier.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError
from kora.email.sender import OutgoingAttachment, OutgoingEmail
from kora.email.templates import render
from kora.models.common import utcnow
from kora.models.identity import Company
from kora.models.organization import FiscalYear
from kora.models.partners import Partner
from kora.models.sales import DocKind, DocStatus, SalesDocument, SalesDocumentEmail
from kora.sales import pdf as sales_pdf
from kora.sales import service

# Libellés commerciaux du gabarit d'email (kind_label du document).
_KIND_LABELS = {
    DocKind.QUOTE.value: {"fr": "devis", "en": "quote"},
    DocKind.INVOICE.value: {"fr": "facture", "en": "invoice"},
    DocKind.CREDIT_NOTE.value: {"fr": "avoir", "en": "credit note"},
}


@dataclass(frozen=True)
class DocumentEmailData:
    """Envoi demandé : le document visé, un destinataire explicite facultatif
    (sinon l'email de la fiche du tier) et un message personnalisé facultatif."""

    document_id: uuid.UUID
    to: str | None = None
    note: str | None = None


def emails_count_for_documents(
    session: Session, company_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Nombre d'envois déjà enregistrés par document (une requête GROUP BY)."""
    if not document_ids:
        return {}
    rows = session.execute(
        select(SalesDocumentEmail.document_id, func.count().label("total"))
        .where(
            SalesDocumentEmail.tenant_id == company_id,
            SalesDocumentEmail.document_id.in_(document_ids),
        )
        .group_by(SalesDocumentEmail.document_id)
    )
    return {row.document_id: int(row.total) for row in rows}


def list_emails(
    session: Session,
    company_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SalesDocumentEmail], int]:
    """Historique des envois d'un document (immuable), du plus récent au plus
    ancien ; renvoie (items, total)."""
    scope = (
        SalesDocumentEmail.tenant_id == company_id,
        SalesDocumentEmail.document_id == document_id,
    )
    total = session.execute(
        select(func.count()).select_from(SalesDocumentEmail).where(*scope)
    ).scalar_one()
    items = list(
        session.execute(
            select(SalesDocumentEmail)
            .where(*scope)
            .order_by(SalesDocumentEmail.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return items, total


def create_email_send(
    session: Session, actor: Actor, data: DocumentEmailData
) -> SalesDocumentEmail:
    """Enregistre un envoi (destinataire figé, note facultative) et journalise
    l'acte. L'email est programmé PAR LA ROUTE après le commit : une panne de la
    file n'annule pas l'enregistrement (`enqueue_best_effort`)."""
    document, _ = service.get_document(session, actor.company_id, data.document_id)
    if document.status == DocStatus.DRAFT.value or document.number is None:
        raise ConflictError(
            "Un brouillon n'a pas de PDF ni de numéro : émettez d'abord le document."
        )
    if document.status == DocStatus.CANCELLED.value:
        raise ConflictError("Une facture annulée ne peut plus être envoyée au client.")
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == document.partner_id
        )
    ).scalar_one()
    destinataire = (data.to or "").strip() or (partner.email or "").strip()
    if not destinataire:
        raise BusinessRuleError(
            "Le tier n'a pas d'adresse email : complétez sa fiche ou saisissez un destinataire."
        )
    envoi = SalesDocumentEmail(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        document_id=document.id,
        partner_id=document.partner_id,
        email_to=destinataire,
        note=(data.note or "").strip() or None,
        created_by_user_id=actor.user_id,
    )
    session.add(envoi)
    record_event(
        session,
        action="sales_document.emailed",
        entity_type="sales_document",
        entity_id=document.id,
        payload={
            "numero": document.number,
            "destinataire": destinataire,
            "type": document.doc_kind,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return envoi


def _numero_affichage(document: SalesDocument, fiscal_year: FiscalYear) -> str:
    """Numéro d'affichage d'un document : même convention que le PDF (4B-bis)."""
    return sales_pdf.format_document_number(
        document.doc_kind, fiscal_year.start_date, document.number or 0
    )


def prepare_email(session: Session, send_id: uuid.UUID) -> OutgoingEmail:
    """Compose l'email du document depuis l'état persisté (chargé par le worker,
    tenant explicitement lié à la session pour la RLS), rend le PDF depuis les
    instantanés et l'attache. LookupError si l'envoi a disparu ; ValueError si
    le document est devenu non envoyable (annulé) : le worker abandonne sans
    réessai. La langue de l'email est le français : langue commerciale des
    clients visés (PME guinéennes) — un gabarit par locale du tier est une
    évolution future."""
    envoi = session.execute(
        select(SalesDocumentEmail).where(SalesDocumentEmail.id == send_id)
    ).scalar_one_or_none()
    if envoi is None:
        raise LookupError(f"envoi {send_id} introuvable : abandon")
    document, lines = service.get_document(session, envoi.tenant_id, envoi.document_id)
    if document.status == DocStatus.CANCELLED.value:
        raise ValueError(f"facture {document.number} annulée depuis la mise en file : abandon")
    if document.status == DocStatus.DRAFT.value or document.number is None:
        raise ValueError(f"document {envoi.document_id} redevenu brouillon : abandon")
    partner = session.execute(
        select(Partner).where(Partner.tenant_id == envoi.tenant_id, Partner.id == envoi.partner_id)
    ).scalar_one()
    company = session.get_one(Company, envoi.tenant_id)
    fiscal_year = session.get_one(FiscalYear, document.fiscal_year_id)

    origin_number: str | None = None
    if document.origin_document_id is not None:
        origin = session.execute(
            select(SalesDocument).where(
                SalesDocument.id == document.origin_document_id,
                SalesDocument.tenant_id == envoi.tenant_id,
            )
        ).scalar_one_or_none()
        if origin is not None and origin.number is not None:
            origin_fiscal = session.get_one(FiscalYear, origin.fiscal_year_id)
            origin_number = sales_pdf.format_document_number(
                origin.doc_kind, origin_fiscal.start_date, origin.number
            )
    content = sales_pdf.render_document(
        document,
        lines,
        fiscal_year,
        origin_number=origin_number,
        generated_at=utcnow(),
    )
    filename = sales_pdf.filename_document(document, fiscal_year)
    numero = _numero_affichage(document, fiscal_year)
    montant = f"{document.total_ttc:,}".replace(",", " ")
    kind_label = _KIND_LABELS.get(document.doc_kind, {})
    note_extra = (
        f"\n\nMessage de « {company.legal_name or company.trade_name} » :\n{envoi.note}"
        if envoi.note
        else ""
    )
    email = render(
        "sales_document",
        "fr",
        to=envoi.email_to,
        partner_name=partner.name,
        company=company.legal_name or company.trade_name or "",
        kind=kind_label.get("fr", "document"),
        number=numero,
        issued_on=document.issued_on.isoformat() if document.issued_on else "",
        amount=montant,
        currency=document.currency,
        note_extra=note_extra,
    )
    attachment = OutgoingAttachment.from_bytes(filename, content, "application/pdf")
    return OutgoingEmail(
        to=email.to,
        subject=email.subject,
        text=email.text,
        html=email.html,
        attachments=(attachment,),
    )
