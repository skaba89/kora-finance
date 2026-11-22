"""Factures et avoirs fournisseurs (Phase 4F) : cycle de vie et numérotation sans trou.

Règles portées par le service (et la base quand possible) — miroir exact du
module ventes (Phase 4B) :
- un brouillon n'est jamais numéroté : modifiable et supprimable librement, sans
  consommer de numéro — c'est la condition structurelle du sans-trou ;
- la numérotation est définitive et transactionnelle : compteur verrouillé (FOR UPDATE),
  incrément dans la même transaction que l'émission — un échec ou un ROLLBACK restaure
  le compteur, donc aucun trou, même sous concurrence. La numérotation interne Kora
  trace le classeur d'achats ; le numéro imprimé par le fournisseur est conservé
  séparément dans `reference` (pièce justificative) ;
- une facture fournisseur annulée (par avoir) conserve son numéro : jamais de
  réutilisation ;
- les montants (HT, TVA récupérable, TTC) sont toujours recalculés par le service à
  partir des lignes — jamais saisis par l'appelant ; les taux de TVA sont re-résolus à
  la date du document (le taux daté actif ce jour-là fait foi) ;
- les mentions du fournisseur et de l'émetteur sont figées à l'émission dans les
  instantanés JSONB (tier et dossier) — même règle dure qu'en ventes (4B-bis,
  ARBITRAGE KF-16) : l'émission refuse de naître sans les mentions fiscales
  (NIU/NCC et adresse du fournisseur, NIF et adresse de l'émetteur) ;
- l'ordre de verrous est « document puis exercice puis compteur », aligné sur le
  grand livre : pas d'interblocage possible entre les deux modules ;
- aucune écriture comptable n'est générée ici : la comptabilisation est un acte
  explicite du comptable (permission `entries:post`) — mais une facture fournisseur
  déjà comptabilisée ne s'annule pas sans contre-passation préalable de son écriture
  (interlock symétrique de celui des décaissements).
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
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import TaxRate
from kora.models.common import utcnow
from kora.models.identity import Company
from kora.models.partners import Partner
from kora.models.purchases import (
    PurchaseDocKind,
    PurchaseDocStatus,
    PurchaseDocument,
    PurchaseDocumentLine,
    PurchasePaymentAllocation,
)
from kora.models.sales import (
    MAX_LINES_PER_DOCUMENT,
    DocumentSequence,
    compute_line_ht,
    compute_line_tax,
)
from kora.tenancy.module_config import require_enabled_module
from kora.tenancy.modules import Module

NUMBERED_KINDS = (PurchaseDocKind.SUPPLIER_INVOICE, PurchaseDocKind.SUPPLIER_CREDIT_NOTE)

# Champs d'en-tête modifiables par PATCH sur un brouillon (convention du dépôt).
_EDITABLE_FIELDS = ("due_on", "notes", "reference")


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
    notes: str | None = None
    reference: str | None = None
    origin_document_id: uuid.UUID | None = None
    reverses_document_id: uuid.UUID | None = None


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def get_document(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[PurchaseDocument, list[PurchaseDocumentLine]]:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    document = session.execute(
        select(PurchaseDocument).where(
            PurchaseDocument.id == document_id, PurchaseDocument.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document introuvable dans ce dossier.")
    lines = list(
        session.execute(
            select(PurchaseDocumentLine)
            .where(PurchaseDocumentLine.document_id == document.id)
            .order_by(PurchaseDocumentLine.line_no)
        ).scalars()
    )
    return document, lines


def _lock_document(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> PurchaseDocument:
    """Verrou de ligne : deux transitions simultanées sur un même document se
    sérialisent (même protocole que entries._lock_entry)."""
    document = session.execute(
        select(PurchaseDocument)
        .where(PurchaseDocument.id == document_id, PurchaseDocument.tenant_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document introuvable dans ce dossier.")
    return document


def _require_draft(document: PurchaseDocument) -> None:
    if document.status != PurchaseDocStatus.DRAFT.value:
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
    document: PurchaseDocument,
    data_lines: tuple[LineData, ...],
    *,
    day: date,
) -> list[PurchaseDocumentLine]:
    """Remplace intégralement les lignes d'un brouillon et recalcule les montants.
    Les montants stockés dérivent toujours des lignes : jamais de total saisi."""
    if not data_lines:
        raise BusinessRuleError("Un document comporte au moins une ligne.")
    if len(data_lines) > MAX_LINES_PER_DOCUMENT:
        raise BusinessRuleError(f"Un document comporte au plus {MAX_LINES_PER_DOCUMENT} lignes.")
    for stale in list(
        session.execute(
            select(PurchaseDocumentLine).where(PurchaseDocumentLine.document_id == document.id)
        ).scalars()
    ):
        session.delete(stale)
    session.flush()  # les suppressions précèdent les réinsertions (unicité line_no)
    lines: list[PurchaseDocumentLine] = []
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
        line = PurchaseDocumentLine(
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


def _recalcule_montants(lines: list[PurchaseDocumentLine], document: PurchaseDocument) -> None:
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
    """Mentions complémentaires manquantes, signalées sans bloquer : les mentions
    fiscales qui bloquent l'émission sont vérifiées séparément (règle dure 4B-bis
    étendue aux achats)."""
    warnings: list[str] = []
    if not partner.rccm:
        warnings.append("Le tier n'a pas de RCCM.")
    if not company.rccm:
        warnings.append("Le dossier n'a pas de RCCM (mention légale de l'émetteur).")
    return warnings


def _exige_facture_sans_reglement(
    session: Session, company_id: uuid.UUID, invoice_id: uuid.UUID
) -> None:
    """Une facture fournisseur qui porte des décaissements ne peut pas être annulée :
    ni sans avoir, ni par avoir annulateur — l'annulation d'une facture payée
    détruirait l'argent versé. Les décaissements se suppriment d'abord (chacun est
    journalisé), puis l'annulation redevient possible."""
    a_un_reglement = session.execute(
        select(PurchasePaymentAllocation.id)
        .where(
            PurchasePaymentAllocation.tenant_id == company_id,
            PurchasePaymentAllocation.document_id == invoice_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if a_un_reglement is not None:
        raise ConflictError(
            "Cette facture porte des décaissements : supprimez-les (journalisés) "
            "avant de l'annuler."
        )


def _mentions_obligatoires_manquantes(partner: Partner, company: Company) -> list[str]:
    """Règle dure (4B-bis, ARBITRAGE_COMPTABLE.md KF-16, étendue aux achats) : les
    mentions fiscales exigées sur une facture d'achat conforme — NIU/NCC et adresse
    du fournisseur, NIF et adresse de l'émetteur. La raison sociale est toujours
    présente (colonne non nulle). Leur absence empêche l'émission : la pièce
    justificative du classeur d'achats ne peut jamais être un document fiscal
    incomplet."""
    manquantes: list[str] = []
    if not partner.tax_id:
        manquantes.append("le NIU/NCC ou NIF du fournisseur (fiche tier)")
    if not partner.address:
        manquantes.append("l'adresse du fournisseur (fiche tier)")
    if not company.nif:
        manquantes.append("le NIF de l'émetteur (dossier)")
    if not company.address:
        manquantes.append("l'adresse de l'émetteur (dossier)")
    return manquantes


def _next_doc_number(
    session: Session, company_id: uuid.UUID, doc_kind: PurchaseDocKind, fiscal_year_id: uuid.UUID
) -> int:
    """Attribue le numéro suivant du compteur verrouillé. Même protocole que
    accounting.entries._next_number : upsert inoffensif, FOR UPDATE, incrément dans
    la transaction courante — le ROLLBACK d'une numérotation échouée restaure le
    compteur, donc aucun trou, même sous forte concurrence. La séquence est partagée
    avec les ventes (même table, type distinct) : les achats ont leur propre suite
    continue par exercice."""
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
    session: Session, company_id: uuid.UUID, document: PurchaseDocument
) -> None:
    """Un avoir fournisseur référence la facture d'origine (même dossier, même
    fournisseur) ; l'annulation totale lie l'avoir à sa facture via
    `reverses_document_id`."""
    if document.doc_kind != PurchaseDocKind.SUPPLIER_CREDIT_NOTE.value:
        if document.reverses_document_id is not None:
            raise BusinessRuleError(
                "Seul un avoir fournisseur peut annuler une facture fournisseur "
                "(reverses_document_id)."
            )
        return
    if document.origin_document_id is None:
        raise BusinessRuleError(
            "Un avoir fournisseur référence obligatoirement la facture d'origine."
        )
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
            select(PurchaseDocument.id).where(
                PurchaseDocument.reverses_document_id == document.reverses_document_id,
                PurchaseDocument.tenant_id == company_id,
            )
        ).scalar_one_or_none()
        if deja_annulee is not None and deja_annulee != document.id:
            raise ConflictError("Cette facture est déjà annulée par un avoir de contrepassation.")
    invoice = session.execute(
        select(PurchaseDocument).where(
            PurchaseDocument.id == document.origin_document_id,
            PurchaseDocument.tenant_id == company_id,
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Facture d'origine introuvable dans ce dossier.")
    if invoice.partner_id != document.partner_id:
        raise BusinessRuleError(
            "L'avoir porte sur un fournisseur différent de celui de la facture d'origine."
        )


def create_document(session: Session, actor: Actor, data: DocumentData) -> PurchaseDocument:
    """Crée un brouillon : jamais numéroté, jamais comptabilisé. L'exercice du
    brouillon est celui d'aujourd'hui ; il sera fixé à la date d'émission au moment
    de la numérotation (un brouillon de décembre émis en janvier change d'exercice)."""
    try:
        doc_kind = PurchaseDocKind(data.doc_kind)
    except ValueError as exc:
        raise BusinessRuleError(
            "Type de document inconnu (supplier_invoice, supplier_credit_note)."
        ) from exc
    if doc_kind != PurchaseDocKind.SUPPLIER_CREDIT_NOTE:
        require_enabled_module(session, actor.company_id, Module.PURCHASES)
    partner = _partner(session, actor.company_id, data.partner_id)
    if not partner.is_supplier:
        raise BusinessRuleError(
            "Ce tier n'est pas un fournisseur : cochez « fournisseur » sur sa fiche."
        )
    if not partner.is_active:
        raise BusinessRuleError(
            "Le tier est désactivé : réactivez-le avant d'enregistrer un achat."
        )
    company = session.get_one(Company, actor.company_id)
    today = utcnow().date()
    fiscal_year = _fiscal_year_for(session, actor.company_id, today)
    if data.due_on is not None and data.due_on < today:
        raise BusinessRuleError("L'échéance d'un document ne peut pas être passée.")
    document = PurchaseDocument(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        doc_kind=doc_kind.value,
        fiscal_year_id=fiscal_year.id,
        status=PurchaseDocStatus.DRAFT.value,
        partner_id=partner.id,
        currency=company.currency,
        due_on=data.due_on,
        notes=_clean(data.notes),
        reference=_clean(data.reference),
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
        action="purchase_document.created",
        entity_type="purchase_document",
        entity_id=document.id,
        payload={"type": doc_kind.value, "tier": partner.name, "total_ttc": document.total_ttc},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return document


def update_draft(
    session: Session, actor: Actor, document_id: uuid.UUID, changes: dict[str, object]
) -> PurchaseDocument:
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
        action="purchase_document.updated",
        entity_type="purchase_document",
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
        action="purchase_document.deleted",
        entity_type="purchase_document",
        entity_id=document_id,
        payload={"type": doc_kind, "total_ttc": total_ttc},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()


def _number_and_emit(
    session: Session,
    actor: Actor,
    document: PurchaseDocument,
    *,
    day: date,
) -> tuple[PurchaseDocument, list[str]]:
    """Cœur transactionnel de la numérotation : verrou document → verrou exercice
    (FOR UPDATE, protocole commun avec le grand livre) → verrou compteur → numéro →
    instantanés → statut → commit. Toute erreur en aval du compteur est un ROLLBACK :
    le numéro est restauré, aucun trou."""
    doc_kind = PurchaseDocKind(document.doc_kind)
    fiscal_year = _fiscal_year_for(session, actor.company_id, day, lock=True)
    lines = list(
        session.execute(
            select(PurchaseDocumentLine)
            .where(PurchaseDocumentLine.document_id == document.id)
            .order_by(PurchaseDocumentLine.line_no)
        ).scalars()
    )
    if not lines:
        raise BusinessRuleError("Un document comporte au moins une ligne.")
    partner = _partner(session, actor.company_id, document.partner_id)
    if not partner.is_supplier:
        raise BusinessRuleError(
            "Ce tier n'est pas un fournisseur : cochez « fournisseur » sur sa fiche."
        )
    if not partner.is_active:
        raise BusinessRuleError(
            "Le tier est désactivé : réactivez-le avant d'enregistrer un achat."
        )
    company = session.get_one(Company, actor.company_id)
    if document.due_on is not None and document.due_on < day:
        raise BusinessRuleError("L'échéance d'une facture ne peut pas précéder sa date d'émission.")
    # Règle dure (4B-bis étendue) : la pièce d'achat naît conforme ou ne naît pas.
    # Contrôle AVANT le compteur : rien à restaurer, aucune numérotation consommée.
    if manquantes := _mentions_obligatoires_manquantes(partner, company):
        raise BusinessRuleError(
            "Émission refusée : mentions obligatoires manquantes pour une facture "
            "d'achat conforme — " + ", ".join(manquantes) + "."
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
    invoice: PurchaseDocument | None = None
    if (
        doc_kind is PurchaseDocKind.SUPPLIER_CREDIT_NOTE
        and document.reverses_document_id is not None
    ):
        invoice = session.execute(
            select(PurchaseDocument)
            .where(
                PurchaseDocument.id == document.reverses_document_id,
                PurchaseDocument.tenant_id == actor.company_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if invoice is None or invoice.status != PurchaseDocStatus.ISSUED.value:
            raise ConflictError("La facture à annuler doit être émise (et non déjà annulée).")
        # Une facture déjà lettrée par des décaissements ne s'annule pas.
        _exige_facture_sans_reglement(session, actor.company_id, invoice.id)
    number = _next_doc_number(session, actor.company_id, doc_kind, fiscal_year.id)
    document.fiscal_year_id = fiscal_year.id
    document.status = PurchaseDocStatus.ISSUED.value
    document.number = number
    document.issued_on = day
    document.issued_by_user_id = actor.user_id
    document.partner_snapshot = _partner_snapshot(partner)
    document.issuer_snapshot = _issuer(company)
    if invoice is not None:
        invoice.status = PurchaseDocStatus.CANCELLED.value
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Conflit d'unicité sur le numéro du document.") from exc
    record_event(
        session,
        action="purchase_document.issued",
        entity_type="purchase_document",
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
) -> tuple[PurchaseDocument, list[str]]:
    """Enregistrement définitif d'une facture ou d'un avoir fournisseur : numéro
    consommé, mentions figées, avoir annulateur → facture CANCELLED. Irréversible."""
    document = _lock_document(session, actor.company_id, document_id)
    _require_draft(document)
    return _number_and_emit(
        session,
        actor,
        document,
        day=issued_on if issued_on is not None else utcnow().date(),
    )


def cancel_supplier_invoice(
    session: Session, actor: Actor, invoice_id: uuid.UUID
) -> PurchaseDocument:
    """Annulation sans avoir (erreur de saisie sur une pièce jamais payée) : le
    numéro est conservé, jamais réutilisé. Une facture fournisseur réellement
    contestée s'annule par un avoir fournisseur (émission de l'avoir annulateur →
    facture CANCELLED automatiquement). Une facture comptabilisée refuse de
    s'annuler tant que son écriture est vivante : elle se contre-passe d'abord au
    grand livre, sinon la charge disparaîtrait des comptes sans jamais avoir été
    créditée."""
    document = _lock_document(session, actor.company_id, invoice_id)
    if document.doc_kind != PurchaseDocKind.SUPPLIER_INVOICE.value:
        raise BusinessRuleError("Cette action s'applique aux factures fournisseurs.")
    if document.status != PurchaseDocStatus.ISSUED.value:
        raise ConflictError("Seule une facture émise peut être annulée.")
    # Une facture déjà lettrée par des décaissements ne s'annule pas.
    _exige_facture_sans_reglement(session, actor.company_id, document.id)
    # Une facture comptabilisée s'annule après contre-passation de son écriture.
    if (
        document.entry_id is not None
        and reversal_id_of(session, actor.company_id, document.entry_id) is None
    ):
        raise ConflictError(
            "Cette facture est comptabilisée : contre-passez son écriture "
            "(grand livre) avant de l'annuler."
        )
    document.status = PurchaseDocStatus.CANCELLED.value
    record_event(
        session,
        action="purchase_document.cancelled",
        entity_type="purchase_document",
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
) -> tuple[list[PurchaseDocument], int]:
    """Liste paginée et filtrée ; renvoie (items, total)."""
    query = select(PurchaseDocument).where(PurchaseDocument.tenant_id == company_id)
    count = (
        select(func.count())
        .select_from(PurchaseDocument)
        .where(PurchaseDocument.tenant_id == company_id)
    )
    if doc_kind is not None:
        query = query.where(PurchaseDocument.doc_kind == doc_kind)
        count = count.where(PurchaseDocument.doc_kind == doc_kind)
    if status is not None:
        query = query.where(PurchaseDocument.status == status)
        count = count.where(PurchaseDocument.status == status)
    if partner_id is not None:
        query = query.where(PurchaseDocument.partner_id == partner_id)
        count = count.where(PurchaseDocument.partner_id == partner_id)
    if search and search.strip():
        needle = search.strip().lower()
        clauses = []
        if needle.isdigit():
            clauses.append(PurchaseDocument.number == int(needle))
        tier_ids = select(Partner.id).where(
            Partner.tenant_id == company_id,
            func.lower(Partner.name).like(f"%{needle}%"),
        )
        clauses.append(PurchaseDocument.partner_id.in_(tier_ids))
        combined = clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1]
        query = query.where(combined)
        count = count.where(combined)
    total = session.execute(count).scalar_one()
    items = list(
        session.execute(
            query.order_by(PurchaseDocument.created_at.desc()).limit(limit).offset(offset)
        ).scalars()
    )
    return items, total


def format_document_number(doc_kind: str, fiscal_year_start: date, number: int) -> str:
    """Numéro d'affichage des documents d'achat : FACH-année-00042 (facture) et
    AVF-année-00042 (avoir), sur le même principe que FAC/DEV/AV en ventes."""
    prefix = "FACH" if doc_kind == PurchaseDocKind.SUPPLIER_INVOICE.value else "AVF"
    return f"{prefix}-{fiscal_year_start.year}-{number:05d}"
