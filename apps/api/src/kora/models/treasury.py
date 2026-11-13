"""Tables tenant de la trésorerie : comptes financiers et mouvements.

Un compte financier (banque, caisse, portefeuille Mobile Money) est le miroir opérationnel
d'un compte du plan comptable (52x banques, 57x caisses) : son solde n'est jamais stocké,
il est toujours recalculé depuis les lignes validées de ce compte comptable. Une seule
source de vérité (le grand livre) ; la trésorerie ne peut jamais diverger du TFT.

Chaque mouvement (dépôt, retrait, frais bancaires, virement interne) crée atomiquement
une écriture validée du journal de trésorerie : le mouvement est la trace opérationnelle,
l'écriture est la vérité comptable. Les mouvements sont immuables (déclencheur) : une
erreur se corrige par un mouvement inverse, jamais par réécriture.

Garanties portées par la base (migration 0011) :
- RLS sur les deux tables : un dossier ne voit que ses comptes ;
- un mouvement référence une écriture du même dossier et ne peut être ni modifié ni
  supprimé ;
- cohérence kind/direction : un dépôt débite le compte, un retrait ou des frais le
  créditent, un virement interne est porté par deux mouvements liés.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk
from kora.models.ledger import MAX_LINE_AMOUNT


class FinancialAccountKind(StrEnum):
    BANQUE = "BANQUE"
    CAISSE = "CAISSE"
    MOBILE_MONEY = "MOBILE_MONEY"


class MovementKind(StrEnum):
    DEPOT = "DEPOT"
    RETRAIT = "RETRAIT"
    VIREMENT_INTERNE = "VIREMENT_INTERNE"
    FRAIS = "FRAIS"


class MovementDirection(StrEnum):
    """Effet du mouvement sur le solde du compte financier (GNF, unités mineures)."""

    DEBIT = "DEBIT"  # entrée de fonds
    CREDIT = "CREDIT"  # sortie de fonds


class FinancialAccount(Base):
    """Compte financier d'un dossier : banque, caisse ou portefeuille Mobile Money.

    Le compte comptable lié (52x/57x) porte le solde ; les opérateurs Mobile Money sont
    normalisés par pays (ORANGE_MONEY_GN, MTN_MOMO_GN…) pour préparer les connecteurs
    de la sous-phase 3D.
    """

    __tablename__ = "financial_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    # Opérateur Mobile Money (ex. ORANGE_MONEY_GN) ; NULL pour une banque ou une caisse.
    operator: Mapped[str | None] = mapped_column(String(24))
    # Numéro masqué pour l'affichage (jamais de données bancaires complètes : "****-1234").
    account_number_masked: Mapped[str | None] = mapped_column(String(40))
    # Compte du plan comptable qui porte le solde (52x banque, 57x caisse).
    gl_account_id: Mapped[uuid.UUID]
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        # Cible des clés étrangères composites (mouvements).
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("kind IN ('BANQUE', 'CAISSE', 'MOBILE_MONEY')", name="kind_valid"),
        CheckConstraint(
            "(kind = 'MOBILE_MONEY' AND operator IS NOT NULL AND operator ~ '^[A-Z0-9_]{2,24}$')"
            " OR (kind <> 'MOBILE_MONEY' AND operator IS NULL)",
            name="operator_matches_kind",
        ),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "account_number_masked IS NULL OR length(trim(account_number_masked)) > 0",
            name="masked_number_not_blank",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "gl_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_financial_accounts_tenant_kind", "tenant_id", "kind"),
    )


class FinancialMovement(Base):
    """Mouvement de trésorerie : trace opérationnelle d'une écriture validée.

    Un dépôt débite le compte financier, un retrait ou des frais le créditent ; un
    virement interne crée deux mouvements (crédit sur la source, débit sur la
    destination) liés par `opposite_movement_id` et portés par une seule écriture.
    Le compte de contrepartie (capital, ventes, charges…) est imposé par l'utilisateur :
    la trésorerie n'invente jamais une contrepartie comptable.
    """

    __tablename__ = "financial_movements"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    financial_account_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[int] = mapped_column(BigInteger)
    movement_date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(200))
    # Compte de contrepartie (dépôt/retrait/frais) ; NULL pour un virement interne.
    counterpart_account_id: Mapped[uuid.UUID | None]
    # Mouvement miroir (virement interne uniquement) : crédit source ↔ débit destination.
    opposite_movement_id: Mapped[uuid.UUID | None]
    # Écriture validée qui porte la vérité comptable du mouvement.
    entry_id: Mapped[uuid.UUID]
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "kind IN ('DEPOT', 'RETRAIT', 'VIREMENT_INTERNE', 'FRAIS')", name="kind_valid"
        ),
        CheckConstraint("direction IN ('DEBIT', 'CREDIT')", name="direction_valid"),
        # Un dépôt est une entrée ; un retrait ou des frais une sortie ; un virement
        # interne est à la fois (crédit source + débit destination).
        CheckConstraint(
            "(kind IN ('DEPOT') AND direction = 'DEBIT')"
            " OR (kind IN ('RETRAIT', 'FRAIS') AND direction = 'CREDIT')"
            " OR (kind = 'VIREMENT_INTERNE' AND direction IN ('DEBIT', 'CREDIT'))",
            name="direction_matches_kind",
        ),
        CheckConstraint(f"amount > 0 AND amount <= {MAX_LINE_AMOUNT}", name="amount_range"),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        CheckConstraint(
            "(kind = 'VIREMENT_INTERNE' AND counterpart_account_id IS NULL"
            " AND opposite_movement_id IS NOT NULL)"
            " OR (kind <> 'VIREMENT_INTERNE' AND counterpart_account_id IS NOT NULL"
            " AND opposite_movement_id IS NULL)",
            name="links_match_kind",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "financial_account_id"],
            ["financial_accounts.tenant_id", "financial_accounts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterpart_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opposite_movement_id"],
            ["financial_movements.tenant_id", "financial_movements.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_financial_movements_tenant_account_date",
            "tenant_id",
            "financial_account_id",
            "movement_date",
        ),
    )


class StatementFormat(StrEnum):
    OFX = "OFX"
    CSV = "CSV"


class StatementLineStatus(StrEnum):
    """État d'une ligne de relevé face au rapprochement (sous-phase 3C).

    PENDING : à rapprocher. MATCHED : rapprochée d'un mouvement (ou d'une écriture)
    — posé dès 3B, rempli en 3C. IGNORED : écartée par l'utilisateur (frais
    d'agios déjà comptabilisés, doublon d'export bancaire…) ; elle reste dans le
    relevé pour la traçabilité mais n'entrera plus dans aucun rapprochement.
    """

    PENDING = "PENDING"
    MATCHED = "MATCHED"
    IGNORED = "IGNORED"


class BankStatement(Base):
    """Relevé bancaire importé pour un compte financier (sous-phase 3B).

    Le fichier original est conservé chiffré dans le stockage d'objets : les lignes
    lues restent vérifiables (audit, litige avec la banque). L'empreinte SHA-256 du
    fichier refuse le double import du même relevé sur un compte — source classique
    de mouvements comptés deux fois.
    """

    __tablename__ = "bank_statements"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    financial_account_id: Mapped[uuid.UUID]
    filename: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    line_count: Mapped[int] = mapped_column(BigInteger)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    # Objet chiffré du fichier original (pièce de traçabilité, réimportable).
    storage_key: Mapped[str] = mapped_column(String(300))
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Un même fichier importé deux fois sur un compte est refusé (pas de double
        # comptage). Un même fichier sur deux comptes distincts n'est pas impossible
        # (export multi-comptes) : la contrainte porte donc sur le couple.
        UniqueConstraint("tenant_id", "financial_account_id", "sha256"),
        CheckConstraint("format IN ('OFX', 'CSV', 'XLSX')", name="format_valid"),
        CheckConstraint("length(trim(filename)) > 0", name="filename_not_blank"),
        CheckConstraint("line_count > 0", name="line_count_positive"),
        CheckConstraint("period_start <= period_end", name="period_ordered"),
        ForeignKeyConstraint(
            ["tenant_id", "financial_account_id"],
            ["financial_accounts.tenant_id", "financial_accounts.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_bank_statements_tenant_account_created",
            "tenant_id",
            "financial_account_id",
            "created_at",
        ),
    )


class BankStatementLine(Base):
    """Ligne d'un relevé importé : opération vue par la banque, pas encore comptable.

    Le montant est signé du point de vue du titulaire (positif = entrée de fonds) ;
    le contenu métier (date, montant, libellé, référence) est haché pour signaler
    les doublons entre relevés successifs. La ligne est en ajout seul jusqu'à son
    statut : elle ne peut être que rapprochée (3C) ou ignorée, jamais corrigée.
    """

    __tablename__ = "bank_statement_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    statement_id: Mapped[uuid.UUID]
    line_no: Mapped[int] = mapped_column(BigInteger)
    value_date: Mapped[date] = mapped_column(Date)
    # Signé, du point de vue du titulaire : positif = entrée, négatif = sortie.
    amount: Mapped[int] = mapped_column(BigInteger)
    label: Mapped[str] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(60))
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), server_default=text("'PENDING'"))
    # Mouvement (ou écriture) apparié par le rapprochement (3C) ; NULL tant que la
    # ligne n'est pas rapprochée.
    matched_movement_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "statement_id", "line_no"),
        # Un mouvement n'est rapproché qu'une fois (3C, migration 0013) : deux lignes
        # — même de deux relevés distincts — ne peuvent pas désigner le même
        # mouvement, sinon l'opération serait comptée deux fois. Les NULL restent
        # libres (lignes non rapprochées).
        UniqueConstraint("tenant_id", "matched_movement_id"),
        CheckConstraint("status IN ('PENDING', 'MATCHED', 'IGNORED')", name="status_valid"),
        CheckConstraint(f"amount <> 0 AND abs(amount) <= {MAX_LINE_AMOUNT}", name="amount_range"),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint(
            "(status = 'MATCHED' AND matched_movement_id IS NOT NULL)"
            " OR (status <> 'MATCHED' AND matched_movement_id IS NULL)",
            name="match_state_consistent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "statement_id"],
            ["bank_statements.tenant_id", "bank_statements.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "matched_movement_id"],
            ["financial_movements.tenant_id", "financial_movements.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_bank_statement_lines_tenant_statement_date",
            "tenant_id",
            "statement_id",
            "value_date",
        ),
        Index("ix_bank_statement_lines_tenant_hash", "tenant_id", "content_hash"),
    )
