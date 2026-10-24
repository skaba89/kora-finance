"""Identité et rattachements : utilisateurs, cabinets, entreprises (tenants), memberships.

Ces tables sont des tables « plateforme » : elles ne portent pas de `tenant_id` et ne
sont pas soumises à la RLS (l'entreprise *est* le tenant ; un utilisateur appartient à
plusieurs tenants). L'accès y passe exclusivement par les services de `kora.tenancy`
et `kora.auth`, couverts par les tests d'isolation.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk
from kora.tenancy.roles import COMPANY_ROLES, FIRM_ROLES


def _in(column: str, values: tuple[str, ...]) -> str:
    # str() et non repr() : repr() d'un StrEnum donne « <Role.X: 'X'> ».
    return f"{column} IN ({', '.join(f"'{v!s}'" for v in values)})"


class LegalForm(StrEnum):
    """Formes juridiques (Acte uniforme OHADA + entreprise individuelle).

    À valider par un expert-comptable guinéen : liste et libellés usuels en Guinée.
    """

    EI = "EI"  # Entreprise individuelle / entreprenant
    SNC = "SNC"
    SCS = "SCS"
    SARL = "SARL"
    SARLU = "SARLU"
    SA = "SA"
    SAU = "SAU"
    SAS = "SAS"
    SASU = "SASU"
    GIE = "GIE"
    SUCCURSALE = "SUCCURSALE"
    AUTRE = "AUTRE"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Toujours normalisé en minuscules par le service (unicité insensible à la casse).
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(String(5), server_default="fr")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Rôle SUPER_ADMIN : administration de la plateforme (abonnements, support).
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failed_login_count: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Incrémenté pour invalider tous les jetons d'accès émis (déconnexion globale…).
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")

    # 2FA TOTP : secret chiffré (Fernet), jamais en clair.
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Dernier pas de temps TOTP accepté : un code ne peut pas être rejoué.
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("locale IN ('fr', 'en')", name="locale_supported"),
    )


class Firm(Base):
    """Cabinet comptable : gère plusieurs dossiers d'entreprises."""

    __tablename__ = "firms"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class FirmMembership(Base):
    __tablename__ = "firm_memberships"

    id: Mapped[uuid.UUID] = uuid_pk()
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("firm_id", "user_id"),
        CheckConstraint(_in("role", FIRM_ROLES), name="role_valid"),
    )


class Company(Base):
    """Dossier d'entreprise = tenant. Toutes les données comptables y sont rattachées."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = uuid_pk()
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str | None] = mapped_column(String(200))
    legal_form: Mapped[str] = mapped_column(String(16))
    # Formats RCCM et NIF guinéens : à valider par un expert ; stockés tels que saisis.
    rccm: Mapped[str | None] = mapped_column(String(64))
    nif: Mapped[str | None] = mapped_column(String(64))
    # Code ISO 4217. GNF par défaut (0 décimale).
    currency: Mapped[str] = mapped_column(String(3), server_default="GNF")
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    # Cabinet gestionnaire du dossier, le cas échéant.
    firm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("firms.id", ondelete="RESTRICT"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    firm: Mapped[Firm | None] = relationship()

    __table_args__ = (
        CheckConstraint(_in("legal_form", tuple(LegalForm)), name="legal_form_valid"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        CheckConstraint("length(trim(legal_name)) > 0", name="legal_name_not_blank"),
    )


class CompanyMembership(Base):
    """Rôle d'un utilisateur de la PME sur son dossier."""

    __tablename__ = "company_memberships"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("company_id", "user_id"),
        CheckConstraint(_in("role", COMPANY_ROLES), name="role_valid"),
    )


class FirmAssignment(Base):
    """Affectation d'un collaborateur de cabinet à un dossier client du cabinet.

    Un CABINET_ADMIN accède à tous les dossiers du cabinet ; un CABINET_COLLABORATEUR
    uniquement à ceux qui lui sont affectés.
    """

    __tablename__ = "firm_assignments"

    id: Mapped[uuid.UUID] = uuid_pk()
    firm_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("firm_memberships.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (UniqueConstraint("firm_membership_id", "company_id"),)


class RefreshToken(Base):
    """Jeton de rafraîchissement opaque, stocké haché, avec rotation par famille.

    Présenter un jeton déjà utilisé révoque toute sa famille (vol présumé).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at_column()


class RecoveryCode(Base):
    """Code de secours 2FA à usage unique (stocké haché)."""

    __tablename__ = "recovery_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class EmailTokenPurpose(StrEnum):
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 (finalité du jeton, pas un secret)
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


class EmailToken(Base):
    """Jeton à usage unique envoyé par email (réinitialisation, vérification d'adresse).

    Seule l'empreinte SHA-256 est stockée : une fuite de la base ne donne aucun lien
    utilisable.
    """

    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    # Adresse à laquelle le lien a été envoyé : une vérification ne vaut que pour elle.
    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint(_in("purpose", tuple(EmailTokenPurpose)), name="purpose_valid"),
    )


class Invitation(Base):
    """Invitation d'une personne sans compte Kora à rejoindre un dossier.

    Le jeton n'existe qu'au moment de l'envoi (empreinte stockée) ; un renvoi en génère
    un nouveau et invalide le précédent lien.
    """

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32))
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    locale: Mapped[str] = mapped_column(String(5), server_default="fr")
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(_in("role", COMPANY_ROLES), name="role_valid"),
        CheckConstraint("locale IN ('fr', 'en')", name="locale_supported"),
        # Une seule invitation en cours par adresse et par dossier.
        Index(
            "uq_invitations_pending_company_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )
