"""Devis, factures et avoirs (Phase 4B) : cycle de vie et numérotation sans trou.

Règles portées par le service (et la base quand possible) :
- un brouillon n'est jamais numéroté : modifiable et supprimable librement, sans
  consommer de numéro — c'est la condition structurelle du sans-trou ;
- la numérotation est définitive et transactionnelle : compteur verrouillé (FOR UPDATE),
  incrément dans la même transaction que le passage de statut — un échec ou un ROLLBACK
  restaure le compteur, donc aucun trou, même sous concurrence. Une facture est numérotée
  à l'émission, un devis à l'envoi, un avoir à son émission ;
- une facture annulée (par avoir) ou un devis refusé conservent leur numéro : jamais de
  réutilisation ;
- les montants (HT, TVA, TTC) sont toujours recalculés par le service à partir des
  lignes — jamais saisis par l'appelant ; les taux de TVA sont re-résolus à la date
  d'émission (le taux daté actif ce jour-là fait foi) ;
- les mentions légales exigées sur les factures guinéennes sont figées à l'émission
  dans les instantanés JSONB (tier et émetteur) — et depuis 4B-bis, une facture ou
  un avoir refuse de naître sans les mentions fiscales (règle dure, ARBITRAGE
  KF-16) : le PDF conforme ne peut jamais produire un document fiscal incomplet ;
- l'ordre de verrous est « document puis exercice puis compteur », aligné sur le
  grand livre (« écriture puis exercice puis numérotation ») : pas d'interblocage
  possible entre les deux modules ;
- aucune écriture comptable n'est générée ici : l'intégration comptable est un
  acte explicite de la Phase 4E (permission `entries:post`) — mais une facture
  déjà comptabilisée ne s'annule pas sans contre-passation préalable de son
  écriture (interlock symétrique de celui des règlements).
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor, _fiscal_year_for, reversal_id_of
from kora.audit.service import record_event
from kora.core import quota
from kora.core.config import get_settings
from kora.core.errors import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
)
from kora.exports.service import MEDIA_TYPES, ExportFile
from kora.models.accounting import TaxRate
from kora.models.common import utcnow
from kora.models.identity import Company
from kora.models.organization import FiscalYear
from kora.models.partners import Partner
from kora.models.sales import (
    MAX_LINES_PER_DOCUMENT,
    DocKind,
    DocStatus,
    DocumentSequence,
    SalesDocument,
    SalesDocumentLine,
    SalesPaymentAllocation,
    compute_line_ht,
    compute_line_tax,
)
from kora.sales import pdf as sales_pdf

NUMBERED_KINDS = (DocKind.INVOICE, DocKind.CREDIT_NOTE)

# Champs d'en-tête modifiables par PATCH sur un brouillon (convention du dépôt).
_EDITABLE_FIELDS = ("due_on", "valid_until", "notes")


@dataclass(frozen=True)
class LineData:
    """Ligne saisie : quantité en millièmes (2,5 = 2500), prix unitaire HT en unités
    mineures de la devise du dossier, remise en points de base."""

    label: str
    quantity: int
    unit_price_ht: int
    discount_bp: int = 0
    tax_rate_id: uuid.UUID | None = None
    tax_exempt_reason: str | None = None


@dataclass(frozen=True)
class DocumentData:
    doc_kind: str
    partner_id: uuid.UUID
    lines: tuple[LineData, ...]
    due_on: date | None = None
    valid_until: date | None = None
    notes: str | None = None
    origin_document_id: uuid.UUID | None = None
    reverses_document_id: uuid.UUID | None = None


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def get_document(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[SalesDocument, list[SalesDocumentLine]]:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    document = session.execute(
        select(SalesDocument).where(
            SalesDocument.id == document_id, SalesDocument.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document introuvable dans ce dossier.")
    lines = list(
        session.execute(
            select(SalesDocumentLine)
            .where(SalesDocumentLine.document_id == document.id)
            .order_by(SalesDocumentLine.line_no)
        ).scalars()
    )
    return document, lines


def _lock_document(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> SalesDocument:
    """Verrou de ligne : deux transitions simultanées sur un même document se
    sérialisent (même protocole que entries._lock_entry)."""
    document = session.execute(
        select(SalesDocument)
        .where(SalesDocument.id == document_id, SalesDocument.tenant_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document introuvable dans ce dossier.")
    return document


def _require_draft(document: SalesDocument) -> None:
    if document.status != DocStatus.DRAFT.value:
        raise ConflictError(
            "Seul un brouillon peut être modifié : les documents numérotés sont figés."
        )


def _partner(session: Session, company_id: uuid.UUID, partner_id: uuid.UUID) -> Partner:
    partner = session.execute(
        select(Partner).where(Partner.id == partner_id, Partner.tenant_id == company_id)
    ).scalar_one_or_none()
    if partner is None:
        raise NotFoundError("Tier introuvable dans ce dossier.")
    return partner


def _tax_rate(session: Session, company_id: uuid.UUID, tax_rate_id: uuid.UUID, day: date) -> int:
    """Résout le taux (points de base) actif pour le jour donné : le taux daté qui
    fait foi est celui valable à la date du document (motif TaxRate, migration 0003)."""
    rate = session.execute(
        select(TaxRate).where(TaxRate.id == tax_rate_id, TaxRate.tenant_id == company_id)
    ).scalar_one_or_none()
    if rate is None:
        raise NotFoundError("Taux de taxe introuvable dans le dossier.")
    if rate.valid_from > day or (rate.valid_to is not None and rate.valid_to < day):
        raise BusinessRuleError(f"Le taux « {rate.label} » n'est pas actif au {day:%d/%m/%Y}.")
    return rate.rate_basis_points


def _write_lines(
    session: Session,
    company_id: uuid.UUID,
    document: SalesDocument,
    data_lines: tuple[LineData, ...],
    *,
    day: date,
) -> list[SalesDocumentLine]:
    """Remplace intégralement les lignes d'un brouillon et recalcule les montants.
    Les montants stockés dérivent toujours des lignes : jamais de total saisi."""
    if not data_lines:
        raise BusinessRuleError("Un document comporte au moins une ligne.")
    if len(data_lines) > MAX_LINES_PER_DOCUMENT:
        raise BusinessRuleError(f"Un document comporte au plus {MAX_LINES_PER_DOCUMENT} lignes.")
    for stale in list(
        session.execute(
            select(SalesDocumentLine).where(SalesDocumentLine.document_id == document.id)
        ).scalars()
    ):
        session.delete(stale)
    session.flush()  # les suppressions précèdent les réinsertions (unicité line_no)
    lines: list[SalesDocumentLine] = []
    for index, data in enumerate(data_lines, start=1):
        label = _clean(data.label)
        if label is None:
            raise BusinessRuleError(f"La désignation de la ligne {index} est vide.")
        if data.quantity <= 0:
            raise BusinessRuleError(f"La quantité de la ligne {index} doit être positive.")
        if data.unit_price_ht < 0:
            raise BusinessRuleError(
                f"Le prix unitaire de la ligne {index} ne peut pas être négatif."
            )
        if not 0 <= data.discount_bp <= 10_000:
            raise BusinessRuleError(f"La remise de la ligne {index} doit être entre 0 et 100 %.")
        if data.tax_rate_id is not None and data.tax_exempt_reason is not None:
            raise BusinessRuleError(
                f"La ligne {index} porte un taux et un motif d'exonération : "
                "l'un ou l'autre, pas les deux."
            )
        tax_bp: int | None = None
        if data.tax_rate_id is not None:
            tax_bp = _tax_rate(session, company_id, data.tax_rate_id, day)
        elif data.tax_exempt_reason is None:
            raise BusinessRuleError(
                f"La ligne {index} doit porter un taux de taxe ou un motif d'exonération."
            )
        line = SalesDocumentLine(
            id=uuid.uuid4(),
            tenant_id=company_id,
            document_id=document.id,
            line_no=index,
            label=label,
            quantity=data.quantity,
            unit_price_ht=data.unit_price_ht,
            discount_bp=data.discount_bp,
            tax_rate_id=data.tax_rate_id,
            tax_bp_snapshot=tax_bp,
            tax_exempt_reason=_clean(data.tax_exempt_reason),
        )
        session.add(line)
        lines.append(line)
    _recalcule_montants(lines, document)
    return lines


def _recalcule_montants(lines: list[SalesDocumentLine], document: SalesDocument) -> None:
    """Recalcule chaque ligne puis les totaux de l'en-tête : les montants stockés
    dérivent toujours des lignes, jamais d'une saisie appelant."""
    total_ht = 0
    total_tax = 0
    for line in lines:
        line.line_ht = compute_line_ht(line.quantity, line.unit_price_ht, line.discount_bp)
        line.line_tax = (
            compute_line_tax(line.line_ht, line.tax_bp_snapshot)
            if line.tax_bp_snapshot is not None
            else 0
        )
        line.line_ttc = line.line_ht + line.line_tax
        total_ht += line.line_ht
        total_tax += line.line_tax
    document.total_ht = total_ht
    document.total_tax = total_tax
    document.total_ttc = total_ht + total_tax


def _issuer(company: Company) -> dict[str, str | None]:
    return {
        "nom": company.legal_name,
        "rccm": company.rccm,
        "nif": company.nif,
        "adresse": company.address,
        "ville": company.city,
        "telephone": company.phone,
    }


def _partner_snapshot(partner: Partner) -> dict[str, str | None]:
    return {
        "nom": partner.name,
        "niu": partner.tax_id,
        "rccm": partner.rccm,
        "adresse": partner.address,
    }


def _emission_warnings(partner: Partner, company: Company) -> list[str]:
    """Mentions manquantes signalées à l'émission. Depuis 4B-bis, les mentions
    fiscales (NIU/NCC, adresses, NIF) sont exigées à l'émission d'une facture ou
    d'un avoir (règle dure) : pour ces documents, restent ici les mentions
    complémentaires (RCCM) ; pour un devis — document commercial, pas fiscal —
    tous les avertissements restent non bloquants."""
    warnings: list[str] = []
    if not partner.tax_id:
        warnings.append("Le tier n'a pas de NIU/NCC ou NIF.")
    if not partner.rccm:
        warnings.append("Le tier n'a pas de RCCM.")
    if not partner.address:
        warnings.append("Le tier n'a pas d'adresse.")
    if not company.rccm:
        warnings.append("Le dossier n'a pas de RCCM (mention légale de l'émetteur).")
    if not company.nif:
        warnings.append("Le dossier n'a pas de NIF (mention légale de l'émetteur).")
    return warnings


def _exige_facture_sans_reglement(
    session: Session, company_id: uuid.UUID, invoice_id: uuid.UUID
) -> None:
    """Une facture qui porte des règlements (4C) ne peut pas être annulée : ni
    sans avoir, ni par avoir annulateur — l'annulation d'une facture payée
    détruirait de l'argent reçu. Les règlements se suppriment d'abord (chacun
    est journalisé), puis l'annulation redevient possible."""
    a_un_reglement = session.execute(
        select(SalesPaymentAllocation.id)
        .where(
            SalesPaymentAllocation.tenant_id == company_id,
            SalesPaymentAllocation.document_id == invoice_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if a_un_reglement is not None:
        raise ConflictError(
            "Cette facture porte des règlements : supprimez-les (journalisés) avant de l'annuler."
        )


def _mentions_obligatoires_manquantes(partner: Partner, company: Company) -> list[str]:
    """Règle dure (4B-bis, ARBITRAGE_COMPTABLE.md KF-16) : les mentions fiscales
    exigées sur une facture conforme — NIU/NCC et adresse du client, NIF et adresse
    de l'émetteur. La raison sociale est toujours présente (colonne non nulle).
    Leur absence empêche l'émission d'une facture ou d'un avoir : le PDF conforme
    ne peut jamais produire un document fiscal incomplet."""
    manquantes: list[str] = []
    if not partner.tax_id:
        manquantes.append("le NIU/NCC ou NIF du client (fiche tier)")
    if not partner.address:
        manquantes.append("l'adresse du client (fiche tier)")
    if not company.nif:
        manquantes.append("le NIF de l'émetteur (dossier)")
    if not company.address:
        manquantes.append("l'adresse de l'émetteur (dossier)")
    return manquantes


def _next_doc_number(
    session: Session, company_id: uuid.UUID, doc_kind: DocKind, fiscal_year_id: uuid.UUID
) -> int:
    """Attribue le numéro suivant du compteur verrouillé. Même protocole que
    accounting.entries._next_number : upsert inoffensif, FOR UPDATE, incrément dans
    la transaction courante — le ROLLBACK d'une numérotation échouée restaure le
    compteur, donc aucun trou, même sous forte concurrence."""
    session.execute(
        pg_insert(DocumentSequence)
        .values(tenant_id=company_id, doc_kind=doc_kind.value, fiscal_year_id=fiscal_year_id)
        .on_conflict_do_nothing()
    )
    sequence = session.execute(
        select(DocumentSequence)
        .where(
            DocumentSequence.tenant_id == company_id,
            DocumentSequence.doc_kind == doc_kind.value,
            DocumentSequence.fiscal_year_id == fiscal_year_id,
        )
        .with_for_update()
    ).scalar_one()
    sequence.last_number += 1
    return sequence.last_number


def _check_credit_note_links(
    session: Session, company_id: uuid.UUID, document: SalesDocument
) -> None:
    """Un avoir référence la facture d'origine (même dossier, même tier, émise) ;
    l'annulation totale lie l'avoir à sa facture via `reverses_document_id`."""
    if document.doc_kind != DocKind.CREDIT_NOTE.value:
        if document.reverses_document_id is not None:
            raise BusinessRuleError(
                "Seul un avoir peut annuler une facture (reverses_document_id)."
            )
        return
    if document.origin_document_id is None:
        raise BusinessRuleError("Un avoir référence obligatoirement la facture d'origine.")
    if (
        document.reverses_document_id is not None
        and document.reverses_document_id != document.origin_document_id
    ):
        raise BusinessRuleError(
            "L'annulation totale (reverses_document_id) doit désigner la facture "
            "d'origine de l'avoir."
        )
    if document.reverses_document_id is not None:
        # Une facture n'est annulée qu'une fois : un seul avoir de contrepassation
        # totale peut exister (la base le garantit aussi par unicité).
        deja_annulee = session.execute(
            select(SalesDocument.id).where(
                SalesDocument.reverses_document_id == document.reverses_document_id,
                SalesDocument.tenant_id == company_id,
            )
        ).scalar_one_or_none()
        if deja_annulee is not None and deja_annulee != document.id:
            raise ConflictError("Cette facture est déjà annulée par un avoir de contrepassation.")
    invoice = session.execute(
        select(SalesDocument).where(
            SalesDocument.id == document.origin_document_id,
            SalesDocument.tenant_id == company_id,
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Facture d'origine introuvable dans ce dossier.")
    if invoice.partner_id != document.partner_id:
        raise BusinessRuleError(
            "L'avoir porte sur un tier différent de celui de la facture d'origine."
        )


def create_document(session: Session, actor: Actor, data: DocumentData) -> SalesDocument:
    """Crée un brouillon : jamais numéroté, jamais comptabilisé. L'exercice du
    brouillon est celui d'aujourd'hui ; il sera fixé à la date d'émission au moment
    de la numérotation (un brouillon de décembre émis en janvier change d'exercice)."""
    try:
        doc_kind = DocKind(data.doc_kind)
    except ValueError as exc:
        raise BusinessRuleError("Type de document inconnu (quote, invoice, credit_note).") from exc
    partner = _partner(session, actor.company_id, data.partner_id)
    if not partner.is_active:
        raise BusinessRuleError("Le tier est désactivé : réactivez-le avant facturation.")
    company = session.get_one(Company, actor.company_id)
    today = utcnow().date()
    fiscal_year = _fiscal_year_for(session, actor.company_id, today)
    if data.due_on is not None and data.due_on < today:
        raise BusinessRuleError("L'échéance d'un document ne peut pas être passée.")
    document = SalesDocument(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        doc_kind=doc_kind.value,
        fiscal_year_id=fiscal_year.id,
        status=DocStatus.DRAFT.value,
        partner_id=partner.id,
        currency=company.currency,
        due_on=data.due_on,
        valid_until=data.valid_until,
        notes=_clean(data.notes),
        origin_document_id=data.origin_document_id,
        reverses_document_id=data.reverses_document_id,
        created_by_user_id=actor.user_id,
    )
    session.add(document)
    # Contrôles de liens AVANT le flush : le refus d'un second avoir annulateur
    # est un 409 propre, pas une erreur d'intégrité brute.
    _check_credit_note_links(session, actor.company_id, document)
    _write_lines(session, actor.company_id, document, data.lines, day=today)
    record_event(
        session,
        action="sales_document.created",
        entity_type="sales_document",
        entity_id=document.id,
        payload={"type": doc_kind.value, "tier": partner.name, "total_ttc": document.total_ttc},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document


def update_draft(
    session: Session, actor: Actor, document_id: uuid.UUID, changes: dict[str, object]
) -> SalesDocument:
    """Mise à jour partielle d'un brouillon : champs d'en-tête et remplacement
    complet des lignes (clé « lines », tuple de LineData, motif entries.update_draft)."""
    if not changes:
        raise BusinessRuleError("Aucune modification fournie.")
    document = _lock_document(session, actor.company_id, document_id)
    _require_draft(document)
    unknown = set(changes) - set(_EDITABLE_FIELDS) - {"lines"}
    if unknown:
        raise BusinessRuleError(f"Champs inconnus ou non modifiables : {sorted(unknown)}.")
    changed: list[str] = []
    for field_name in _EDITABLE_FIELDS:
        if field_name not in changes:
            continue
        raw = changes[field_name]
        value = _clean(raw) if isinstance(raw, str) else raw
        if getattr(document, field_name) != value:
            setattr(document, field_name, value)
            changed.append(field_name)
    if "lines" in changes:
        raw_lines = changes["lines"]
        lines = tuple(raw_lines) if isinstance(raw_lines, (list, tuple)) else ()
        _write_lines(session, actor.company_id, document, lines, day=utcnow().date())
        changed.append("lines")
    record_event(
        session,
        action="sales_document.updated",
        entity_type="sales_document",
        entity_id=document.id,
        payload={"champs": changed or ["aucun"]},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document


def delete_draft(session: Session, actor: Actor, document_id: uuid.UUID) -> None:
    """Supprime un brouillon : aucun numéro n'a été consommé — un brouillon abandonné
    ne crée jamais de trou dans la numérotation."""
    document = _lock_document(session, actor.company_id, document_id)
    _require_draft(document)
    doc_kind = document.doc_kind
    total_ttc = document.total_ttc
    session.delete(document)
    record_event(
        session,
        action="sales_document.deleted",
        entity_type="sales_document",
        entity_id=document_id,
        payload={"type": doc_kind, "total_ttc": total_ttc},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()


def _verifier_cible_numerotation(doc_kind: DocKind, target_status: str) -> None:
    """Cible de numérotation cohérente avec le type : un devis est numéroté à
    l'envoi, une facture ou un avoir à l'émission."""
    if doc_kind not in NUMBERED_KINDS and doc_kind is not DocKind.QUOTE:
        raise BusinessRuleError("Type de document inconnu.")
    if doc_kind is DocKind.QUOTE and target_status != DocStatus.SENT.value:
        raise BusinessRuleError("Un devis est numéroté à l'envoi.")
    if doc_kind in NUMBERED_KINDS and target_status != DocStatus.ISSUED.value:
        raise BusinessRuleError("Une facture ou un avoir est numéroté à l'émission.")


def _number_and_emit(
    session: Session,
    actor: Actor,
    document: SalesDocument,
    *,
    day: date,
    target_status: str,
) -> tuple[SalesDocument, list[str]]:
    """Cœur transactionnel de la numérotation : verrou document → verrou exercice
    (FOR UPDATE, protocole commun avec le grand livre) → verrou compteur → numéro →
    instantanés → statut → commit. Toute erreur en aval du compteur est un ROLLBACK :
    le numéro est restauré, aucun trou."""
    doc_kind = DocKind(document.doc_kind)
    _verifier_cible_numerotation(doc_kind, target_status)
    fiscal_year = _fiscal_year_for(session, actor.company_id, day, lock=True)
    lines = list(
        session.execute(
            select(SalesDocumentLine)
            .where(SalesDocumentLine.document_id == document.id)
            .order_by(SalesDocumentLine.line_no)
        ).scalars()
    )
    if not lines:
        raise BusinessRuleError("Un document comporte au moins une ligne.")
    partner = _partner(session, actor.company_id, document.partner_id)
    if not partner.is_active:
        raise BusinessRuleError("Le tier est désactivé : réactivez-le avant facturation.")
    company = session.get_one(Company, actor.company_id)
    if document.due_on is not None and doc_kind is DocKind.INVOICE and document.due_on < day:
        raise BusinessRuleError("L'échéance d'une facture ne peut pas précéder sa date d'émission.")
    # Règle dure (4B-bis) : facture et avoir naissent conformes ou ne naissent pas.
    # Contrôle AVANT le compteur : rien à restaurer, aucune numérotation consommée.
    if doc_kind in NUMBERED_KINDS and (
        manquantes := _mentions_obligatoires_manquantes(partner, company)
    ):
        raise BusinessRuleError(
            "Émission refusée : mentions obligatoires manquantes pour une facture "
            "conforme — " + ", ".join(manquantes) + "."
        )
    # Les taux datés qui font foi sont ceux actifs à la date du document.
    for line in lines:
        if line.tax_rate_id is not None:
            line.tax_bp_snapshot = _tax_rate(session, actor.company_id, line.tax_rate_id, day)
    _recalcule_montants(lines, document)
    warnings = _emission_warnings(partner, company)
    # Un avoir annulateur clôt sa facture dans la même transaction : la facture
    # passe CANCELLED exactement quand l'avoir reçoit son numéro. La facture est
    # verrouillée avant le compteur (ordre document → exercice → compteur → facture).
    invoice: SalesDocument | None = None
    if doc_kind is DocKind.CREDIT_NOTE and document.reverses_document_id is not None:
        invoice = session.execute(
            select(SalesDocument)
            .where(
                SalesDocument.id == document.reverses_document_id,
                SalesDocument.tenant_id == actor.company_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if invoice is None or invoice.status != DocStatus.ISSUED.value:
            raise ConflictError("La facture à annuler doit être émise (et non déjà annulée).")
        # Une facture déjà lettrée par des règlements (4C) ne s'annule pas.
        _exige_facture_sans_reglement(session, actor.company_id, invoice.id)
    number = _next_doc_number(session, actor.company_id, doc_kind, fiscal_year.id)
    document.fiscal_year_id = fiscal_year.id
    document.status = target_status
    document.number = number
    document.issued_on = day
    document.issued_by_user_id = actor.user_id
    document.partner_snapshot = _partner_snapshot(partner)
    document.issuer_snapshot = _issuer(company)
    if invoice is not None:
        invoice.status = DocStatus.CANCELLED.value
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Conflit d'unicité sur le numéro du document.") from exc
    record_event(
        session,
        action="sales_document.issued"
        if target_status == DocStatus.ISSUED.value
        else "sales_document.sent",
        entity_type="sales_document",
        entity_id=document.id,
        payload={
            "type": document.doc_kind,
            "numero": number,
            "total_ttc": document.total_ttc,
            "avertissements": warnings,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document, warnings


def issue_document(
    session: Session, actor: Actor, document_id: uuid.UUID, *, issued_on: date | None = None
) -> tuple[SalesDocument, list[str]]:
    """Émission définitive d'une facture ou d'un avoir : numéro consommé, mentions
    figées, avoir annulateur → facture CANCELLED. Irréversible."""
    document = _lock_document(session, actor.company_id, document_id)
    _require_draft(document)
    if DocKind(document.doc_kind) not in NUMBERED_KINDS:
        raise BusinessRuleError("Un devis n'est pas émis : envoyez-le (il est numéroté à l'envoi).")
    return _number_and_emit(
        session,
        actor,
        document,
        day=issued_on if issued_on is not None else utcnow().date(),
        target_status=DocStatus.ISSUED.value,
    )


def send_quote(
    session: Session, actor: Actor, quote_id: uuid.UUID
) -> tuple[SalesDocument, list[str]]:
    """Envoi d'un devis au client : numérotation définitive (chronologie sans trou),
    mentions figées. Un devis refusé conserve son numéro."""
    document = _lock_document(session, actor.company_id, quote_id)
    _require_draft(document)
    _check_credit_note_links(session, actor.company_id, document)
    return _number_and_emit(
        session, actor, document, day=utcnow().date(), target_status=DocStatus.SENT.value
    )


def decide_quote(
    session: Session, actor: Actor, quote_id: uuid.UUID, accepted: bool
) -> SalesDocument:
    document = _lock_document(session, actor.company_id, quote_id)
    if document.doc_kind != DocKind.QUOTE.value:
        raise BusinessRuleError("Cette action s'applique aux devis.")
    if document.status != DocStatus.SENT.value:
        raise ConflictError("Seul un devis envoyé peut être accepté ou refusé.")
    document.status = DocStatus.ACCEPTED.value if accepted else DocStatus.REJECTED.value
    record_event(
        session,
        action="sales_document.decided",
        entity_type="sales_document",
        entity_id=document.id,
        payload={"accepte": accepted, "numero": document.number},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document


def convert_quote(session: Session, actor: Actor, quote_id: uuid.UUID) -> SalesDocument:
    """Convertit un devis accepté en facture brouillon : lignes copiées, tier
    conservé, devis référencé. La facture naît brouillon — elle ne sera numérotée
    qu'à son émission (les deux séquences restent sans trou indépendamment)."""
    quote = _lock_document(session, actor.company_id, quote_id)
    if quote.doc_kind != DocKind.QUOTE.value:
        raise BusinessRuleError("Cette action s'applique aux devis.")
    if quote.status != DocStatus.ACCEPTED.value:
        raise ConflictError("Seul un devis accepté peut être converti en facture.")
    quote_lines = list(
        session.execute(
            select(SalesDocumentLine)
            .where(SalesDocumentLine.document_id == quote.id)
            .order_by(SalesDocumentLine.line_no)
        ).scalars()
    )
    data_lines = tuple(
        LineData(
            label=line.label,
            quantity=line.quantity,
            unit_price_ht=line.unit_price_ht,
            discount_bp=line.discount_bp,
            tax_rate_id=line.tax_rate_id,
            tax_exempt_reason=line.tax_exempt_reason,
        )
        for line in quote_lines
    )
    return create_document(
        session,
        actor,
        DocumentData(
            doc_kind=DocKind.INVOICE.value,
            partner_id=quote.partner_id,
            lines=data_lines,
            notes=quote.notes,
            origin_document_id=quote.id,
        ),
    )


def cancel_invoice(session: Session, actor: Actor, invoice_id: uuid.UUID) -> SalesDocument:
    """Annulation sans avoir (facture jamais envoyée, erreur de saisie) : le numéro
    est conservé, jamais réutilisé. Une facture envoyée au client s'annule par un
    avoir (émission de l'avoir annulateur → facture CANCELLED automatiquement).
    Une facture comptabilisée (4E) refuse de s'annuler tant que son écriture est
    vivante : elle se contre-passe d'abord au grand livre, sinon la créance
    disparaîtrait des comptes sans jamais avoir été créditée."""
    document = _lock_document(session, actor.company_id, invoice_id)
    if document.doc_kind != DocKind.INVOICE.value:
        raise BusinessRuleError("Cette action s'applique aux factures.")
    if document.status != DocStatus.ISSUED.value:
        raise ConflictError("Seule une facture émise peut être annulée.")
    # Une facture déjà lettrée par des règlements (4C) ne s'annule pas.
    _exige_facture_sans_reglement(session, actor.company_id, document.id)
    # Une facture comptabilisée (4E) s'annule après contre-passation de son écriture.
    if (
        document.entry_id is not None
        and reversal_id_of(session, actor.company_id, document.entry_id) is None
    ):
        raise ConflictError(
            "Cette facture est comptabilisée : contre-passez son écriture "
            "(grand livre) avant de l'annuler."
        )
    document.status = DocStatus.CANCELLED.value
    record_event(
        session,
        action="sales_document.cancelled",
        entity_type="sales_document",
        entity_id=document.id,
        payload={"numero": document.number},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document


def list_documents(
    session: Session,
    company_id: uuid.UUID,
    *,
    doc_kind: str | None = None,
    status: str | None = None,
    partner_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SalesDocument], int]:
    """Liste paginée et filtrée ; renvoie (items, total)."""
    query = select(SalesDocument).where(SalesDocument.tenant_id == company_id)
    count = (
        select(func.count()).select_from(SalesDocument).where(SalesDocument.tenant_id == company_id)
    )
    if doc_kind is not None:
        query = query.where(SalesDocument.doc_kind == doc_kind)
        count = count.where(SalesDocument.doc_kind == doc_kind)
    if status is not None:
        query = query.where(SalesDocument.status == status)
        count = count.where(SalesDocument.status == status)
    if partner_id is not None:
        query = query.where(SalesDocument.partner_id == partner_id)
        count = count.where(SalesDocument.partner_id == partner_id)
    if search and search.strip():
        needle = search.strip().lower()
        clauses = []
        if needle.isdigit():
            clauses.append(SalesDocument.number == int(needle))
        tier_ids = select(Partner.id).where(
            Partner.tenant_id == company_id,
            func.lower(Partner.name).like(f"%{needle}%"),
        )
        clauses.append(SalesDocument.partner_id.in_(tier_ids))
        combined = clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1]
        query = query.where(combined)
        count = count.where(combined)
    total = session.execute(count).scalar_one()
    items = list(
        session.execute(
            query.order_by(SalesDocument.created_at.desc()).limit(limit).offset(offset)
        ).scalars()
    )
    return items, total


def export_document_pdf(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID, actor: Actor
) -> ExportFile:
    """PDF conforme d'un document numéroté (4B-bis) : exclusivement les données
    figées à la numérotation (instantanés émetteur/tier, numéro, lignes, taux) —
    jamais les fiches vivantes. Un brouillon n'a ni numéro ni mentions figées :
    pas de PDF (le document commercial est le PDF numéroté).

    Quota d'exports KF-13 (mêmes compteurs que les exports comptables : la
    génération est synchrone et coûteuse) et journal d'audit : le PDF fait
    partie de la trace du document, comme son émission."""
    document, lines = get_document(session, company_id, document_id)
    if document.number is None:
        raise BusinessRuleError(
            "Le PDF est disponible après numérotation : envoyez le devis ou émettez la facture."
        )
    settings = get_settings()
    user_limit = settings.exports_per_user_per_hour
    if not quota.allowed(
        "export-user", str(actor.user_id), limit=user_limit, window_seconds=quota.HOUR
    ):
        raise TooManyRequestsError(
            f"Limite de {user_limit} exports par heure atteinte pour votre compte.",
            headers={"Retry-After": quota.retry_after(quota.HOUR)},
        )
    company_limit = settings.exports_per_company_per_hour
    if not quota.allowed(
        "export-company", str(company_id), limit=company_limit, window_seconds=quota.HOUR
    ):
        raise TooManyRequestsError(
            f"Limite de {company_limit} exports par heure atteinte pour ce dossier.",
            headers={"Retry-After": quota.retry_after(quota.HOUR)},
        )
    fiscal_year = session.get_one(FiscalYear, document.fiscal_year_id)
    origin_number: str | None = None
    if document.origin_document_id is not None:
        origin = session.execute(
            select(SalesDocument).where(
                SalesDocument.id == document.origin_document_id,
                SalesDocument.tenant_id == company_id,
            )
        ).scalar_one_or_none()
        if origin is not None and origin.number is not None:
            origin_fiscal = session.get_one(FiscalYear, origin.fiscal_year_id)
            origin_number = sales_pdf.format_document_number(
                origin.doc_kind, origin_fiscal.start_date, origin.number
            )
    content = sales_pdf.render_document(
        document, lines, fiscal_year, origin_number=origin_number, generated_at=utcnow()
    )
    filename = sales_pdf.filename_document(document, fiscal_year)
    record_event(
        session,
        action="sales_document.exported",
        entity_type="sales_document",
        entity_id=document.id,
        payload={
            "type": document.doc_kind,
            "numero": sales_pdf.format_document_number(
                document.doc_kind, fiscal_year.start_date, document.number
            ),
            "total_ttc": document.total_ttc,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return ExportFile(content, filename, MEDIA_TYPES["pdf"])
