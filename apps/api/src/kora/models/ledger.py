"""Tables tenant de la comptabilité générale : journaux, écritures, lignes.

Garanties portées par la base elle-même (migration 0005), en plus des services :
- une écriture validée (POSTED) et ses lignes ne peuvent être ni modifiées ni
  supprimées : une erreur se corrige par contre-passation ;
- une écriture ne peut passer à POSTED que si elle est équilibrée (∑ débit = ∑ crédit,
  au moins deux lignes, total non nul) ;
- toutes les références (journal, exercice, compte, écriture) restent dans le même
  dossier grâce à des clés étrangères composites (tenant_id, id).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk

# Montant maximal d'une ligne, en unités mineures (10 000 milliards de GNF). Les sommes
# d'une écriture restent ainsi très en deçà des limites d'un BIGINT.
MAX_LINE_AMOUNT = 10**13
MAX_LINES_PER_ENTRY = 500


class JournalKind(StrEnum):
    ACHATS = "ACHATS"
    VENTES = "VENTES"
    TRESORERIE = "TRESORERIE"
    OPERATIONS_DIVERSES = "OPERATIONS_DIVERSES"
    A_NOUVEAUX = "A_NOUVEAUX"


class EntryStatus(StrEnum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class Journal(Base):
    __tablename__ = "journals"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(8))
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(24))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("code ~ '^[A-Z0-9]{1,8}$'", name="code_format"),
        CheckConstraint(
            "kind IN ('ACHATS', 'VENTES', 'TRESORERIE', 'OPERATIONS_DIVERSES', 'A_NOUVEAUX')",
            name="kind_valid",
        ),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
    )


class JournalEntry(Base):
    """Écriture comptable. Brouillon : modifiable, sans numéro. Validée : numérotée
    (séquence sans trou par journal et par exercice) et immuable."""

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    journal_id: Mapped[uuid.UUID]
    fiscal_year_id: Mapped[uuid.UUID]
    entry_date: Mapped[date] = mapped_column(Date)
    number: Mapped[int | None] = mapped_column(Integer)
    # Référence de la pièce justificative (n° de facture, de reçu…).
    reference: Mapped[str | None] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(8), server_default=EntryStatus.DRAFT.value)
    # Écriture contre-passée par celle-ci (une seule contre-passation par écriture).
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "journal_id", "fiscal_year_id", "number"),
        ForeignKeyConstraint(
            ["tenant_id", "journal_id"], ["journals.tenant_id", "journals.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reversal_of_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('DRAFT', 'POSTED')", name="status_valid"),
        CheckConstraint(
            "(status = 'DRAFT' AND number IS NULL AND posted_at IS NULL) OR "
            "(status = 'POSTED' AND number > 0 AND posted_at IS NOT NULL)",
            name="posting_consistent",
        ),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        Index("ix_journal_entries_tenant_date", "tenant_id", "entry_date"),
    )


class JournalLine(Base):
    """Ligne d'écriture : un montant au débit *ou* au crédit, en unités mineures."""

    __tablename__ = "journal_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    entry_id: Mapped[uuid.UUID]
    line_no: Mapped[int] = mapped_column(SmallInteger)
    account_id: Mapped[uuid.UUID]
    label: Mapped[str | None] = mapped_column(String(200))
    debit: Mapped[int] = mapped_column(BigInteger, server_default="0")
    credit: Mapped[int] = mapped_column(BigInteger, server_default="0")

    __table_args__ = (
        UniqueConstraint("entry_id", "line_no"),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(
            f"debit BETWEEN 0 AND {MAX_LINE_AMOUNT} AND credit BETWEEN 0 AND {MAX_LINE_AMOUNT}",
            name="amounts_range",
        ),
        # Exactement un des deux montants est non nul.
        CheckConstraint("(debit = 0) <> (credit = 0)", name="one_side"),
        CheckConstraint(f"line_no BETWEEN 1 AND {MAX_LINES_PER_ENTRY}", name="line_no_range"),
        Index("ix_journal_lines_tenant_account", "tenant_id", "account_id"),
    )


class JournalSequence(Base):
    """Dernier numéro attribué par journal et par exercice. Verrouillée (FOR UPDATE) à
    chaque validation : deux validations simultanées ne peuvent pas obtenir le même
    numéro, et un numéro n'est consommé que si la validation aboutit (pas de trou)."""

    __tablename__ = "journal_sequences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "journal_id"], ["journals.tenant_id", "journals.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            ondelete="CASCADE",
        ),
    )
