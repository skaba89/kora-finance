"""Tables tenant du paramétrage comptable : plan de comptes et taux de taxes."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk


class Account(Base):
    """Compte du plan comptable d'un dossier.

    Les comptes de référence (SYSCOHADA) ne peuvent qu'être désactivés ; les comptes
    créés par le dossier (sous-comptes) peuvent être renommés.
    """

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    number: Mapped[str] = mapped_column(String(12))
    label: Mapped[str] = mapped_column(String(200))
    # Référentiel d'origine (ex. SYSCOHADA_REVISE_2017), NULL pour un compte créé par le dossier.
    reference: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        # Cible des clés étrangères composites : un compte n'est référencé que par son dossier.
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("number ~ '^[1-9][0-9]{0,11}$'", name="number_digits"),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
    )


class TaxRate(Base):
    """Taux de taxe daté. Un changement de taux crée une nouvelle version (l'ancienne
    reste applicable à ses dates) : les déclarations passées restent recalculables.

    Les taux sont en points de base (1800 = 18,00 %) : jamais de flottant.
    """

    __tablename__ = "tax_rates"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    rate_basis_points: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    collected_account_number: Mapped[str | None] = mapped_column(String(12))
    deductible_account_number: Mapped[str | None] = mapped_column(String(12))
    # Valeur par défaut non confirmée : à vérifier auprès de la DGI par le dossier.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("rate_basis_points BETWEEN 0 AND 10000", name="rate_range"),
        CheckConstraint("kind IN ('TVA', 'AUTRE')", name="kind_valid"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_ordered"),
        CheckConstraint("code ~ '^[A-Z0-9_]{2,40}$'", name="code_format"),
        # Pour un même code, les périodes de validité ne se chevauchent pas.
        ExcludeConstraint(
            ("tenant_id", "="),
            ("code", "="),
            (text("daterange(valid_from, valid_to, '[]')"), "&&"),
            name="tax_rates_no_overlap",
            using="gist",
        ),
    )
