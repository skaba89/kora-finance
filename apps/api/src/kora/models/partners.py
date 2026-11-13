"""Référentiel des tiers d'un dossier : clients et fournisseurs (Phase 4A).

Un tier est la fiche maître qui portera les factures (4B), les règlements (4C),
les relances (4D) et l'intégration comptable (4E). La fiche n'est jamais supprimée :
elle est désactivée (is_active) — les factures et le lettrage déjà émis doivent rester
rattachés à leur tier. Les mentions obligatoires des factures (ARBITRAGE_COMPTABLE.md)
sont portées dès maintenant : raison sociale (name), NIU/NCC ou NIF (tax_id),
RCCM et adresse.

Le compte de grand livre par défaut (411x client, 401x fournisseur) pré-remplit la
saisie, mais n'est jamais une obligation : une facture peut toujours choisir un autre
compte de tiers du plan du dossier.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # Raison sociale (personne morale) ou nom (personne physique) : mention obligatoire
    # des factures. L'unicité est insensible à la casse (index fonctionnel, migration).
    name: Mapped[str] = mapped_column(String(200))
    is_client: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_supplier: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Mentions obligatoires des factures (ou traces d'identification) — optionnelles
    # à la création, exigées par les factures de 4B le moment venu.
    tax_id: Mapped[str | None] = mapped_column(String(50))  # NIU/NCC ou NIF
    rccm: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    # Coordonnées des relances (4D : email, WhatsApp).
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(30))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    # Comptes de tiers par défaut (411x client, 401x fournisseur) : simple
    # pré-remplissage, jamais une écriture automatique.
    default_client_account_id: Mapped[uuid.UUID | None]
    default_supplier_account_id: Mapped[uuid.UUID | None]
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # Un tier sert au moins à un sens d'échange : client, fournisseur ou les deux.
        CheckConstraint("is_client OR is_supplier", name="at_least_one_kind"),
        CheckConstraint("tax_id IS NULL OR length(trim(tax_id)) > 0", name="tax_id_not_blank"),
        CheckConstraint("rccm IS NULL OR length(trim(rccm)) > 0", name="rccm_not_blank"),
        CheckConstraint("address IS NULL OR length(trim(address)) > 0", name="address_not_blank"),
        CheckConstraint("notes IS NULL OR length(trim(notes)) > 0", name="notes_not_blank"),
        ForeignKeyConstraint(
            ["tenant_id", "default_client_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "default_supplier_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        Index("ix_partners_tenant_name", "tenant_id", "name"),
        # Unicité du nom insensible à la casse dans un dossier (comme la migration).
        Index("uq_partners_tenant_name_lower", "tenant_id", text("lower(name)"), unique=True),
        Index("ix_partners_tenant_client", "tenant_id", "is_client"),
        Index("ix_partners_tenant_supplier", "tenant_id", "is_supplier"),
    )
