"""Référentiel des tiers (Phase 4A) : fiches clients et fournisseurs.

Règles portées par le service (et la base quand possible) :
- un tier sert au moins à un sens : client et/ou fournisseur ;
- le nom est unique dans le dossier, sans tenir compte de la casse ;
- les comptes de tiers par défaut sont des comptes de classe 4 du plan du dossier :
  préfixe 411x pour un compte client, 401x pour un compte fournisseur (sous-comptes
  SYSCOHADA — à valider par un expert-comptable) ; le compte doit être actif ;
- un tier n'est jamais supprimé : il est désactivé (les factures et lettrages
  émis plus tard (4B/4C) doivent rester rattachés à leur fiche).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account
from kora.models.partners import Partner


@dataclass(frozen=True)
class PartnerData:
    name: str
    is_client: bool = False
    is_supplier: bool = False
    tax_id: str | None = None
    rccm: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    contact_name: str | None = None
    default_client_account_id: uuid.UUID | None = None
    default_supplier_account_id: uuid.UUID | None = None
    notes: str | None = None
    is_active: bool = True


# Comptes de tiers SYSCOHADA qui peuvent pré-remplir la saisie (à valider par un
# expert-comptable : clients 4111-4114, fournisseurs 4011-4013 et sous-comptes).
_CLIENT_PREFIX = "411"
_SUPPLIER_PREFIX = "401"

# Champs modifiables par PATCH (convention du dépôt : mise à jour partielle).
_EDITABLE_FIELDS = (
    "name",
    "is_client",
    "is_supplier",
    "tax_id",
    "rccm",
    "address",
    "email",
    "phone",
    "contact_name",
    "default_client_account_id",
    "default_supplier_account_id",
    "notes",
    "is_active",
)


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _account(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, role: str, prefix: str
) -> Account:
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.tenant_id == company_id)
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte introuvable dans le plan comptable du dossier.")
    if not account.number.startswith(prefix):
        attendu = f"{prefix}x"
        raise BusinessRuleError(
            f"Le compte {account.number} ne peut pas pré-remplir un tier {role} : "
            f"choisissez un compte de classe {attendu}."
        )
    if not account.is_active:
        raise BusinessRuleError(f"Le compte {account.number} est désactivé.")
    return account


def get_partner(session: Session, company_id: uuid.UUID, partner_id: uuid.UUID) -> Partner:
    """Lecture bornée au dossier : la RLS force le même filtre côté base."""
    partner = session.execute(
        select(Partner).where(Partner.id == partner_id, Partner.tenant_id == company_id)
    ).scalar_one_or_none()
    if partner is None:
        raise NotFoundError("Tier introuvable dans ce dossier.")
    return partner


def list_partners(
    session: Session,
    company_id: uuid.UUID,
    *,
    kind: str | None = None,
    active: bool | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Partner], int]:
    """Liste paginée et filtrée ; renvoie (items, total)."""
    query = select(Partner).where(Partner.tenant_id == company_id)
    count = select(func.count()).select_from(Partner).where(Partner.tenant_id == company_id)
    if kind == "CLIENT":
        query = query.where(Partner.is_client.is_(True))
        count = count.where(Partner.is_client.is_(True))
    elif kind == "FOURNISSEUR":
        query = query.where(Partner.is_supplier.is_(True))
        count = count.where(Partner.is_supplier.is_(True))
    if active is not None:
        query = query.where(Partner.is_active.is_(active))
        count = count.where(Partner.is_active.is_(active))
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        clause = func.lower(Partner.name).like(needle) | func.lower(
            func.coalesce(Partner.tax_id, "")
        ).like(needle)
        query = query.where(clause)
        count = count.where(clause)
    total = session.execute(count).scalar_one()
    items = list(
        session.execute(query.order_by(Partner.name).limit(limit).offset(offset)).scalars()
    )
    return items, total


def create_partner(session: Session, actor: Actor, data: PartnerData) -> Partner:
    if not data.is_client and not data.is_supplier:
        raise BusinessRuleError("Un tier doit être au moins client ou fournisseur.")
    if data.default_client_account_id is not None:
        _account(session, actor.company_id, data.default_client_account_id, "client", "411")
    if data.default_supplier_account_id is not None:
        _account(session, actor.company_id, data.default_supplier_account_id, "fournisseur", "401")
    partner = Partner(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        name=data.name.strip(),
        is_client=data.is_client,
        is_supplier=data.is_supplier,
        tax_id=_clean(data.tax_id),
        rccm=_clean(data.rccm),
        address=_clean(data.address),
        email=_clean(data.email),
        phone=_clean(data.phone),
        contact_name=_clean(data.contact_name),
        default_client_account_id=data.default_client_account_id,
        default_supplier_account_id=data.default_supplier_account_id,
        notes=_clean(data.notes),
        is_active=data.is_active,
        created_by_user_id=actor.user_id,
    )
    session.add(partner)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Un tier porte déjà ce nom dans ce dossier.") from exc
    record_event(
        session,
        action="partner.created",
        entity_type="partner",
        entity_id=partner.id,
        payload={
            "nom": partner.name,
            "client": partner.is_client,
            "fournisseur": partner.is_supplier,
            "niu": partner.tax_id,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return partner


def update_partner(
    session: Session, actor: Actor, partner_id: uuid.UUID, changes: dict[str, object]
) -> Partner:
    """Mise à jour partielle (champs fournis uniquement, convention PATCH du dépôt).
    Un tier n'est jamais supprimé : is_active porte la désactivation ; les champs
    d'identification restent modifiables (correction d'une faute de frappe sur le
    NIU, par exemple)."""
    if not changes:
        raise BusinessRuleError("Aucune modification fournie.")
    partner = get_partner(session, actor.company_id, partner_id)
    unknown = set(changes) - set(_EDITABLE_FIELDS)
    if unknown:
        raise BusinessRuleError(f"Champs inconnus ou non modifiables : {sorted(unknown)}.")
    next_kinds = {
        "is_client": changes.get("is_client", partner.is_client),
        "is_supplier": changes.get("is_supplier", partner.is_supplier),
    }
    if not next_kinds["is_client"] and not next_kinds["is_supplier"]:
        raise BusinessRuleError("Un tier doit être au moins client ou fournisseur.")
    for field, account_id in (
        ("default_client_account_id", changes.get("default_client_account_id")),
        ("default_supplier_account_id", changes.get("default_supplier_account_id")),
    ):
        value = getattr(partner, field) if field not in changes else account_id
        if value is not None:
            prefix = _CLIENT_PREFIX if field == "default_client_account_id" else _SUPPLIER_PREFIX
            _account(
                session,
                actor.company_id,
                value,  # type: ignore[arg-type]
                "client" if prefix == _CLIENT_PREFIX else "fournisseur",
                prefix,
            )
    changed: list[str] = []
    for field, raw in changes.items():
        value = _clean(raw) if isinstance(raw, str) else raw
        if field == "name" and (value is None or str(value).strip() == ""):
            raise BusinessRuleError("Le nom du tier ne peut pas être vide.")
        if getattr(partner, field) != value:
            setattr(partner, field, value)
            changed.append(field)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Un tier porte déjà ce nom dans ce dossier.") from exc
    record_event(
        session,
        action="partner.updated",
        entity_type="partner",
        entity_id=partner.id,
        payload={"champs": changed or ["aucun"]},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return partner
