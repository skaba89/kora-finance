"""Devis, factures et avoirs d'un dossier (Phase 4B).

Un document de vente (`SalesDocument`) porte le cycle complet : brouillon libre
(jamais numéroté, modifiable, supprimable), émission définitive (numéro consommé,
mentions figées), annulation par avoir. Le numéro est attribué au moment de
l'émission uniquement — c'est la condition structurelle de la numérotation
chronologique sans trou exigée par le cahier des charges : un brouillon abandonné
ne crée jamais de trou, et une annulation conserve le numéro (jamais de réutilisation).

Le compteur (`DocumentSequence`) réplique le protocole éprouvé des journaux
comptables (`JournalSequence`) : verrou de ligne FOR UPDATE, incrément dans la
même transaction que l'émission, compteur restauré par le ROLLBACK en cas d'échec.

Aucune écriture comptable n'est générée par ce module : l'intégration comptable
est un acte explicite de la Phase 4E (permission `entries:post`), qui lie
l'écriture validée au document via `entry_id` (NULL tant que non comptabilisé).
"""

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

# Quantités en millièmes (2,5 heures = 2500) : jamais de flottant.
QUANTITY_SCALE = 1000
# Remise en points de base (1500 = 15,00 %).
MAX_DISCOUNT_BP = 10_000
# Nombre maximal de lignes par document (motif MAX_LINES_PER_ENTRY du grand livre).
MAX_LINES_PER_DOCUMENT = 50


class DocKind(StrEnum):
    QUOTE = "quote"
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"


class DocStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"  # devis envoyé au client
    ACCEPTED = "ACCEPTED"  # devis accepté (convertible en facture)
    REJECTED = "REJECTED"  # devis refusé
    ISSUED = "ISSUED"  # facture ou avoir émis : numéro définitif
    CANCELLED = "CANCELLED"  # facture annulée (par avoir ou correction)


STATUSES_BY_KIND: dict[DocKind, frozenset[DocStatus]] = {
    DocKind.QUOTE: frozenset(
        {DocStatus.DRAFT, DocStatus.SENT, DocStatus.ACCEPTED, DocStatus.REJECTED}
    ),
    DocKind.INVOICE: frozenset({DocStatus.DRAFT, DocStatus.ISSUED, DocStatus.CANCELLED}),
    DocKind.CREDIT_NOTE: frozenset({DocStatus.DRAFT, DocStatus.ISSUED}),
}


def next_status_allowed(kind: DocStatus | str, status: str) -> bool:
    """Vérifie que la paire (type, statut) est valide — reflète la contrainte SQL."""
    try:
        doc_kind = DocKind(kind)
        return DocStatus(status) in STATUSES_BY_KIND[doc_kind]
    except ValueError:
        return False


def compute_line_ht(quantity_milli: int, unit_price_ht: int, discount_bp: int = 0) -> int:
    """Montant HT d'une ligne en unités mineures : quantité (millièmes) × prix unitaire
    HT × (1 - remise), arrondi à l'unité la plus proche à partir de 0,5
    (ROUND_HALF_UP de Decimal, convention comptable)."""
    amount = (
        Decimal(quantity_milli)
        * Decimal(unit_price_ht)
        * Decimal(MAX_DISCOUNT_BP - discount_bp)
        / (Decimal(QUANTITY_SCALE) * Decimal(MAX_DISCOUNT_BP))
    )
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_line_tax(line_ht: int, tax_bp: int) -> int:
    """TVA d'une ligne : HT × taux (points de base, 1800 = 18 %), arrondi comptable."""
    amount = Decimal(line_ht) * Decimal(tax_bp) / Decimal(MAX_DISCOUNT_BP)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class DocumentSequence(Base):
    """Dernier numéro attribué par type de document et par exercice. Verrouillée
    (FOR UPDATE) à chaque émission : deux émissions simultanées ne peuvent pas
    obtenir le même numéro, et un numéro n'est consommé que si l'émission aboutit
    (pas de trou, même en cas d'annulation de la transaction)."""

    __tablename__ = "document_sequences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    doc_kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        CheckConstraint("doc_kind IN ('quote', 'invoice', 'credit_note')", name="doc_kind_valid"),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            ondelete="CASCADE",
        ),
    )


class SalesDocument(Base):
    """En-tête d'un document de vente : devis, facture ou avoir. Les mentions
    légales exigées sur les factures guinéennes sont figées à l'émission dans
    `partner_snapshot` (fiche tier) et `issuer_snapshot` (dossier émetteur) :
    les documents émis restent fidèles même si les fiches changent ensuite."""

    __tablename__ = "sales_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    doc_kind: Mapped[str] = mapped_column(String(16))
    fiscal_year_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(16), server_default=DocStatus.DRAFT.value)
    # NULL en brouillon ; attribué à l'émission, jamais réutilisé (index partiel).
    number: Mapped[int | None] = mapped_column(Integer)
    issued_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    # Validité d'un devis (calculée à la lecture, jamais écrite en base).
    valid_until: Mapped[date | None] = mapped_column(Date)
    partner_id: Mapped[uuid.UUID]
    partner_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    issuer_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    currency: Mapped[str] = mapped_column(String(3), server_default="GNF")
    total_ht: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_tax: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_ttc: Mapped[int] = mapped_column(BigInteger, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    # Devis d'origine d'une facture, facture d'origine d'un avoir.
    origin_document_id: Mapped[uuid.UUID | None]
    # Avoir annulant totalement une facture (unique : une facture ne peut être
    # annulée qu'une fois, par un seul avoir de contrepassation totale).
    reverses_document_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    # Écriture validée qui porte le document en comptabilité (Phase 4E) : NULL
    # tant que le comptable n'a pas comptabilisé — jamais automatique.
    entry_id: Mapped[uuid.UUID | None]
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "(doc_kind, status) IN (('quote','DRAFT'), ('quote','SENT'), ('quote','ACCEPTED'),"
            " ('quote','REJECTED'), ('invoice','DRAFT'), ('invoice','ISSUED'),"
            " ('invoice','CANCELLED'), ('credit_note','DRAFT'), ('credit_note','ISSUED'))",
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
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_sales_documents_tenant_kind", "tenant_id", "doc_kind"),
        Index("ix_sales_documents_tenant_status", "tenant_id", "status"),
        Index("ix_sales_documents_tenant_partner", "tenant_id", "partner_id"),
        Index("ix_sales_documents_tenant_date", "tenant_id", "issued_on"),
        # Unicité du numéro par type et exercice (deuxième barrière derrière le
        # verrou du compteur) — uniquement pour les documents émis.
        Index(
            "uq_sales_documents_number",
            "tenant_id",
            "doc_kind",
            "fiscal_year_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
    )


class SalesDocumentLine(Base):
    """Ligne d'un document : désignation, quantité (millièmes), prix unitaire HT,
    remise en points de base et taux de TVA figé à l'émission. Les montants sont
    recalculés par le service à chaque mutation — jamais saisis par l'appelant."""

    __tablename__ = "sales_document_lines"

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
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        Index("ix_sales_document_lines_tenant_document", "tenant_id", "document_id"),
    )


class PaymentMethod(StrEnum):
    """Mode d'encaissement d'un règlement client. Mobile Money est le premier
    usage réel des PME guinéennes ; les autres modes couvrent la banque et la
    caisse. La liste est bornée : la CHECK SQL refuse tout mode hors énumération."""

    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    MOBILE_MONEY = "MOBILE_MONEY"
    CHECK = "CHECK"
    CARD = "CARD"
    OTHER = "OTHER"


class SalesPayment(Base):
    """Règlement reçu d'un client (Phase 4C) : un encaissement d'un montant
    strictement positif, affecté à une ou plusieurs factures émises du même tier
    (affectations `SalesPaymentAllocation` — le lettrage commercial). Le montant
    du règlement est la somme de ses affectations : le service le recalcule et
    refuse tout excédent sur le solde restant des factures — jamais d'acompte
    flottant non lettré à cette phase (le trop-perçu est une évolution future).

    Le règlement est immuable après création : une erreur se corrige en
    supprimant le règlement (journalisé) puis en le re-saisissant — une fois
    comptabilisé, la suppression exige d'abord la contre-passation de son
    écriture (Phase 4E, permission `entries:post`)."""

    __tablename__ = "sales_payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # Exercice de la date d'encaissement : fixé par le service à partir de
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
    # Écriture validée qui porte l'encaissement en comptabilité (Phase 4E) :
    # NULL tant que non comptabilisé — jamais automatique.
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
        Index("ix_sales_payments_tenant_partner", "tenant_id", "partner_id"),
        Index("ix_sales_payments_tenant_date", "tenant_id", "paid_on"),
    )


class SalesPaymentAllocation(Base):
    """Affectation d'un règlement à une facture (lettrage commercial) : le lien
    qui porte le solde restant dû. Un règlement ne s'affecte qu'une fois à une
    même facture (unicité), et jamais au-delà de son solde (contrôle du service,
    sous verrou FOR UPDATE de la facture — deux règlements concurrents ne peuvent
    pas excéder le TTC ensemble)."""

    __tablename__ = "sales_payment_allocations"

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
            ["sales_payments.tenant_id", "sales_payments.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        Index("ix_sales_payment_allocations_tenant_document", "tenant_id", "document_id"),
        Index("ix_sales_payment_allocations_tenant_payment", "tenant_id", "payment_id"),
    )


class ReminderChannel(StrEnum):
    """Canal d'envoi d'une relance. EMAIL seul pour cette phase : le canal est
    borné par une CHECK SQL ; WhatsApp (API Business) est une évolution future
    qui ajoutera sa valeur à l'énumération et à la CHECK."""

    EMAIL = "EMAIL"


class SalesReminder(Base):
    """Relance d'une facture échue adressée au client (Phase 4D) : un rappel
    documenté, immuable (un email envoyé ne se « désend » pas — aucune
    suppression ni modification), d'un niveau compté par le service (1re, 2e,
    3e relance…) sous verrou de la facture — jamais saisi par l'appelant. Une
    même facture ne reçoit qu'une relance par jour (unicité en base) : pas de
    bombardement du client, et une course concurrente ne crée pas de doublon.
    L'adresse destinataire est figée au moment de l'envoi (traçabilité). Aucune
    écriture comptable : la relance est un acte commercial, pas un fait
    financier."""

    __tablename__ = "sales_reminders"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID]
    partner_id: Mapped[uuid.UUID]
    level: Mapped[int] = mapped_column(SmallInteger)
    reminded_on: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(16))
    email_to: Mapped[str] = mapped_column(String(254))
    note: Mapped[str | None] = mapped_column(Text)
    # Auteur humain des relances manuelles (4D) uniquement : une relance
    # automatique (lot 2) est créée par le planificateur — origine système,
    # NULL. Le NULL distingue structurellement les deux origines.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Une même facture ne reçoit qu'une relance par jour : la course
        # concurrente se sérialise sur ce contraignant (traduit en 409).
        UniqueConstraint("tenant_id", "document_id", "reminded_on"),
        CheckConstraint("level >= 1", name="level_valid"),
        CheckConstraint("channel IN ('EMAIL')", name="channel_valid"),
        CheckConstraint("length(trim(email_to)) > 0", name="email_to_not_blank"),
        CheckConstraint("note IS NULL OR length(trim(note)) > 0", name="note_not_blank"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        Index("ix_sales_reminders_tenant_document", "tenant_id", "document_id"),
        Index("ix_sales_reminders_tenant_partner", "tenant_id", "partner_id"),
        Index("ix_sales_reminders_tenant_date", "tenant_id", "reminded_on"),
    )


class SalesReminderPolicy(Base):
    """Politique de relance automatique du dossier (Phase B, lot 2) : une ligne
    au plus par dossier (upsert — même patron que les réglages de trésorerie).
    `offsets_days` porte l'échéancier d'escalade : les retards (jours après
    l'échéance) auxquels une relance est due — ex. [1, 7, 15] = 1re relance à
    J+1, 2e à J+7, 3e à J+15. Le planificateur (worker) balaye les dossiers et
    crée les relances dues ; la sémantique fine (entiers >= 1, strictement
    croissants, 1 à 6 seuils) est validée par le service. Aucune écriture
    comptable : une relance reste un acte commercial, pas un fait financier."""

    __tablename__ = "sales_reminder_policies"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    offsets_days: Mapped[list[Any]] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("jsonb_typeof(offsets_days) = 'array'", name="offsets_array"),
        CheckConstraint("jsonb_array_length(offsets_days) BETWEEN 1 AND 6", name="offsets_count"),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
    )


class SalesDocumentEmail(Base):
    """Envoi d'un document de vente par email avec son PDF en pièce jointe
    (Phase 4D-bis) : un envoi est un acte commercial documenté et immuable (un
    email parti ne se « désend » pas — aucune suppression ni modification).
    L'adresse destinataire est figée au moment de la demande (traçabilité : le
    tier peut changer d'email ensuite). Contrairement à la relance (4D), un
    même document peut être renvoyé plusieurs fois le même jour (le client
    redemande l'exemplaire) : pas d'unicité quotidienne — le journal d'audit
    et l'historique de la page portent la trace de chaque envoi. Le PDF joint
    est rendu dans le worker depuis les instantanés figés à l'émission. Aucune
    écriture comptable : l'envoi n'est pas un fait financier."""

    __tablename__ = "sales_document_emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID]
    partner_id: Mapped[uuid.UUID]
    email_to: Mapped[str] = mapped_column(String(254))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("length(trim(email_to)) > 0", name="email_to_not_blank"),
        CheckConstraint("note IS NULL OR length(trim(note)) > 0", name="note_not_blank"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        Index("ix_sales_document_emails_tenant_document", "tenant_id", "document_id"),
        Index("ix_sales_document_emails_tenant_partner", "tenant_id", "partner_id"),
    )
