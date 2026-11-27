"""Métadonnées des fichiers d'import comptable en attente de traitement."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, uuid_pk


class ImportBatch(Base):
    """Référence d'un objet chiffré, jamais le contenu du fichier en clair."""

    __tablename__ = "accounting_import_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    format: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    delimiter: Mapped[str] = mapped_column(String(4))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Rapport de précontrôle persisté : NULL tant qu'aucun précontrôle n'a tourné.
    # `stored_issues` borne la volumétrie ; le total réel reste dans `issue_count`.
    precheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    precheck_rows: Mapped[int | None] = mapped_column(BigInteger)
    precheck_entries: Mapped[int | None] = mapped_column(BigInteger)
    precheck_debit: Mapped[int | None] = mapped_column(BigInteger)
    precheck_credit: Mapped[int | None] = mapped_column(BigInteger)
    precheck_valid: Mapped[bool | None] = mapped_column(Boolean)
    precheck_issue_count: Mapped[int | None] = mapped_column(Integer)
    precheck_stored_issues: Mapped[int | None] = mapped_column(Integer)
    # Confirmation humaine : une seule, sous verrou de ligne. Les brouillons générés
    # sont référencés dans `accounting_import_entries` (traçabilité et annulation).
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_entries: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "sha256", "format", "currency", "delimiter"),
        CheckConstraint("format IN ('csv', 'fec', 'xlsx')", name="format_valid"),
        CheckConstraint("currency = 'GNF'", name="currency_valid"),
        CheckConstraint(
            "(format = 'fec' AND delimiter IN ('PIPE', 'TAB')) OR "
            "(format <> 'fec' AND delimiter = 'NONE')",
            name="delimiter_valid",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= CASE WHEN format = 'xlsx' "
            "THEN 16777216 ELSE 33554432 END",
            name="size_valid",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("expires_at > created_at", name="expiry_valid"),
        CheckConstraint(
            "storage_key = 'imports/' || tenant_id::text || '/' || id::text",
            name="storage_key_valid",
        ),
        CheckConstraint("octet_length(wrapped_key) > 0", name="wrapped_key_present"),
        CheckConstraint(
            "(precheck_at IS NULL AND precheck_rows IS NULL AND precheck_entries IS NULL "
            "AND precheck_debit IS NULL AND precheck_credit IS NULL AND precheck_valid IS NULL "
            "AND precheck_issue_count IS NULL AND precheck_stored_issues IS NULL) "
            "OR (precheck_at IS NOT NULL AND precheck_rows IS NOT NULL "
            "AND precheck_entries IS NOT NULL AND precheck_debit IS NOT NULL "
            "AND precheck_credit IS NOT NULL AND precheck_valid IS NOT NULL "
            "AND precheck_issue_count IS NOT NULL AND precheck_stored_issues IS NOT NULL)",
            name="precheck_coherent",
        ),
        CheckConstraint(
            "precheck_issue_count >= 0 AND precheck_stored_issues >= 0 "
            "AND precheck_stored_issues <= precheck_issue_count",
            name="precheck_counts_valid",
        ),
        CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_by_user_id IS NULL AND confirmed_entries IS NULL) "
            "OR (confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL "
            "AND confirmed_entries IS NOT NULL)",
            name="confirmation_coherent",
        ),
        CheckConstraint(
            "confirmed_entries IS NULL OR confirmed_entries >= 1",
            name="confirmed_entries_valid",
        ),
        Index("ix_accounting_import_batches_tenant_expiry", "tenant_id", "expires_at"),
    )


class ImportBatchIssue(Base):
    """Anomalie persistée d'un rapport de précontrôle, bornée et ordonnée."""

    __tablename__ = "accounting_import_issues"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounting_import_batches.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_number: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("seq >= 0", name="seq_valid"),
        CheckConstraint("row_number >= 1", name="row_number_valid"),
        CheckConstraint("octet_length(code) > 0", name="code_present"),
    )


class ImportBatchEntry(Base):
    """Traçabilité d'un batch confirmé : une ligne par brouillon généré.

    Lien purement additif : aucune colonne ni contrainte ajoutée aux écritures.
    La suppression d'un brouillon par son auteur emporte la ligne (CASCADE) —
    l'annulation d'un batch ne visera que les brouillons encore présents. Un
    brouillon ne peut appartenir qu'à un seul batch (unicité dossier + écriture).
    """

    __tablename__ = "accounting_import_entries"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounting_import_batches.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "entry_id"),
    )
