"""Achats : factures et avoirs fournisseurs d'un dossier (Phase 4F).

Miroir du module ventes (Phases 4B/4C/4E) appliqué aux dépenses : une facture
fournisseur (`PurchaseDocument`, `doc_kind = 'supplier_invoice'`) suit le cycle
brouillon libre (jamais numéroté, modifiable, supprimable) → émission définitive
(numéro consommé, mentions figées, TVA récupérable datée) → annulation par avoir
fournisseur. La numérotation partage le compteur `DocumentSequence` du module
ventes (verrou FOR UPDATE, incrément dans la même transaction, compteur restauré
par le ROLLBACK) : la garantie « sans trou » est la même pour les achats que
pour les ventes.

Le règlement (`PurchasePayment`) est un décaissement affecté à une ou plusieurs
factures fournisseurs émises du même tier (affectations `PurchasePaymentAllocation`
— le lettrage commercial fournisseurs) : montant = somme des affectations, jamais
d'excédent sur le solde restant dû, calculé en lecture (TTC moins affectations
moins avoirs partiels émis).

La comptabilisation (`purchase_documents.entry_id`, `purchase_payments.entry_id`)
est un acte explicite du comptable (`entries:post`) : écriture du journal des
achats AC (débit du compte de charge au HT, débit de la TVA récupérable de chaque
taux, crédit du compte de tiers au TTC) et du journal de trésorerie selon le
mode de décaissement (571 caisse / 521 banque / MM) débité au crédit du compte
de tiers. Elle n'est jamais automatique : aucune émission ni aucun règlement
n'écrit en comptabilité.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk
from kora.models.sales import MAX_LINES_PER_DOCUMENT


class PurchaseDocKind(StrEnum):
    """Type d'un document d'achat : la facture reçue du fournisseur, ou l'avoir
    qu'il accorde (remise accordée après facturation, retour de marchandises).
    L'avoir annulateur porte une référence à la facture qu'il annule."""

    SUPPLIER_INVOICE = "supplier_invoice"
    SUPPLIER_CREDIT_NOTE = "supplier_credit_note"


class PurchaseDocStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"  # facture ou avoir fournisseur enregistré : numéro définitif
    CANCELLED = "CANCELLED"  # facture fournisseur annulée (par avoir ou correction)


STATUSES_BY_KIND: dict[PurchaseDocKind, frozenset[PurchaseDocStatus]] = {
    PurchaseDocKind.SUPPLIER_INVOICE: frozenset(
        {PurchaseDocStatus.DRAFT, PurchaseDocStatus.ISSUED, PurchaseDocStatus.CANCELLED}
    ),
    PurchaseDocKind.SUPPLIER_CREDIT_NOTE: frozenset(
        {PurchaseDocStatus.DRAFT, PurchaseDocStatus.ISSUED}
    ),
}


class PurchaseDocument(Base):
    """En-tête d'un document d'achat. Les mentions du fournisseur (NIU/NCC, RCCM,
    adresse) et du dossier émetteur (NIF, adresse) sont figées à l'émission dans
    `partner_snapshot` et `issuer_snapshot` : le document enregistré reste fidèle
    même si les fiches changent ensuite — même règle dure qu'en ventes (l'émission
    refuse de naître sans les mentions obligatoires du fournisseur). `reference`
    porte le numéro imprimé sur la facture du fournisseur (pièce justificative du
    classeur d'achats) ; la numérotation interne Kora reste sans trou."""

    __tablename__ = "purchase_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    doc_kind: Mapped[str] = mapped_column(String(24))
    fiscal_year_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(16), server_default=PurchaseDocStatus.DRAFT.value)
    # NULL en brouillon ; attribué à l'émission, jamais réutilisé (index partiel).
    number: Mapped[int | None] = mapped_column(Integer)
    issued_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    partner_id: Mapped[uuid.UUID]
    # Numéro figurant sur la facture du fournisseur (traçabilité pièce à pièce).
    reference: Mapped[str | None] = mapped_column(String(100))
    partner_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    issuer_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    currency: Mapped[str] = mapped_column(String(3), server_default="GNF")
    total_ht: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_tax: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_ttc: Mapped[int] = mapped_column(BigInteger, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    # Facture d'origine d'un avoir fournisseur.
    origin_document_id: Mapped[uuid.UUID | None]
    # Avoir annulant totalement une facture fournisseur (unique : une facture ne
    # peut être annulée qu'une fois, par un seul avoir de contrepassation totale).
    reverses_document_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    # Écriture validée qui porte le document en comptabilité : NULL tant que le
    # comptable n'a pas comptabilisé — jamais automatique (acte explicite).
    entry_id: Mapped[uuid.UUID | None]
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "(doc_kind, status) IN (('supplier_invoice','DRAFT'), ('supplier_invoice','ISSUED'),"
            " ('supplier_invoice','CANCELLED'), ('supplier_credit_note','DRAFT'),"
            " ('supplier_credit_note','ISSUED'))",
            name="kind_status_valid",
        ),
        # Un document émis porte son numéro et sa date ; un brouillon n'en porte pas.
        CheckConstraint(
            "(status = 'DRAFT' AND number IS NULL AND issued_on IS NULL)"
            " OR (status <> 'DRAFT' AND number IS NOT NULL AND issued_on IS NOT NULL)",
            name="number_follows_emission",
        ),
        CheckConstraint(
            "total_ht >= 0 AND total_tax >= 0 AND total_ttc >= 0", name="totals_non_negative"
        ),
        CheckConstraint("length(trim(currency)) = 3", name="currency_iso4217"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) > 0", name="notes_not_blank"),
        CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0", name="reference_not_blank"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        ForeignKeyConstraint(["issued_by_user_id"], ["users.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "origin_document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_purchase_documents_tenant_kind", "tenant_id", "doc_kind"),
        Index("ix_purchase_documents_tenant_status", "tenant_id", "status"),
        Index("ix_purchase_documents_tenant_partner", "tenant_id", "partner_id"),
        Index("ix_purchase_documents_tenant_date", "tenant_id", "issued_on"),
        # Unicité du numéro par type et exercice (deuxième barrière derrière le
        # verrou du compteur) — uniquement pour les documents émis.
        Index(
            "uq_purchase_documents_number",
            "tenant_id",
            "doc_kind",
            "fiscal_year_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
    )


class PurchaseDocumentLine(Base):
    """Ligne d'un document d'achat : désignation, quantité (millièmes), prix
    unitaire HT, remise en points de base et taux de TVA figé à l'émission (le
    taux daté porte son compte de TVA récupérable — 4452 par défaut). Les
    montants sont recalculés par le service à chaque mutation — jamais saisis."""

    __tablename__ = "purchase_document_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID]
    line_no: Mapped[int] = mapped_column(SmallInteger)
    label: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(BigInteger)  # en millièmes
    unit_price_ht: Mapped[int] = mapped_column(BigInteger)  # unités mineures
    discount_bp: Mapped[int] = mapped_column(Integer, server_default="0")
    # FK simple : le service scoping toujours par (tenant_id, id) et la RLS de
    # tax_rates (migration 0003) complète l'isolation côté base.
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tax_rates.id", ondelete="RESTRICT")
    )
    # Taux figé en points de base à l'émission (1800 = 18 %) ; NULL = exonéré.
    tax_bp_snapshot: Mapped[int | None]
    line_ht: Mapped[int] = mapped_column(BigInteger, server_default="0")
    line_tax: Mapped[int] = mapped_column(BigInteger, server_default="0")
    line_ttc: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # L'exonération est une décision documentée (article du CGI guinéen…).
    tax_exempt_reason: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "line_no"),
        CheckConstraint(f"line_no BETWEEN 1 AND {MAX_LINES_PER_DOCUMENT}", name="line_no_range"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_ht >= 0", name="unit_price_non_negative"),
        CheckConstraint("discount_bp BETWEEN 0 AND 10000", name="discount_bp_range"),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        CheckConstraint(
            "tax_exempt_reason IS NULL OR length(trim(tax_exempt_reason)) > 0",
            name="tax_exempt_reason_not_blank",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        Index("ix_purchase_document_lines_tenant_document", "tenant_id", "document_id"),
    )


class PurchasePayment(Base):
    """Décaissement versé à un fournisseur : un règlement d'un montant
    strictement positif, affecté à une ou plusieurs factures fournisseurs émises
    du même tier (affectations `PurchasePaymentAllocation` — le lettrage
    commercial fournisseurs). Le montant du règlement est la somme de ses
    affectations : le service le recalcule et refuse tout excédent sur le solde
    restant des factures — jamais d'avance flottante non lettrée à cette phase.

    Le règlement est immuable après création : une erreur se corrige en
    supprimant le règlement (journalisé) puis en le re-saisissant — une fois
    comptabilisé, la suppression exige d'abord la contre-passation de son
    écriture (permission `entries:post`)."""

    __tablename__ = "purchase_payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # Exercice de la date de décaissement : fixé par le service à partir de
    # paid_on (l'exercice doit être ouvert — même règle que les documents).
    fiscal_year_id: Mapped[uuid.UUID]
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    # Somme des affectations, en unités mineures (jamais saisi par l'appelant).
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default="GNF")
    partner_id: Mapped[uuid.UUID]
    # Écriture validée qui porte le décaissement en comptabilité : NULL tant que
    # non comptabilisé — jamais automatique (acte explicite).
    entry_id: Mapped[uuid.UUID | None]
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "method IN ('CASH', 'BANK_TRANSFER', 'MOBILE_MONEY', 'CHECK', 'CARD', 'OTHER')",
            name="method_valid",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("length(trim(currency)) = 3", name="currency_iso4217"),
        CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0", name="reference_not_blank"
        ),
        CheckConstraint("notes IS NULL OR length(trim(notes)) > 0", name="notes_not_blank"),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_purchase_payments_tenant_partner", "tenant_id", "partner_id"),
        Index("ix_purchase_payments_tenant_date", "tenant_id", "paid_on"),
    )


class PurchasePaymentAllocation(Base):
    """Affectation d'un décaissement à une facture fournisseur (lettrage
    commercial fournisseurs) : le lien qui porte le solde restant dû. Un
    règlement ne s'affecte qu'une fois à une même facture (unicité), et jamais
    au-delà de son solde (contrôle du service, sous verrou FOR UPDATE de la
    facture — deux règlements concurrents ne peuvent pas excéder le TTC
    ensemble)."""

    __tablename__ = "purchase_payment_allocations"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    payment_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    amount: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("payment_id", "document_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["purchase_payments.tenant_id", "purchase_payments.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        Index("ix_purchase_payment_allocations_tenant_document", "tenant_id", "document_id"),
        Index("ix_purchase_payment_allocations_tenant_payment", "tenant_id", "payment_id"),
    )
