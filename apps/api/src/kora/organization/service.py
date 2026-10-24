"""Cas d'usage : dossiers d'entreprise, membres et exercices comptables."""

import calendar
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth.service import RequestContext, get_user_by_email
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.identity import Company, CompanyMembership, FirmMembership, User
from kora.models.organization import FiscalYear
from kora.tenancy.roles import COMPANY_ROLES, Role

# Durée maximale d'un exercice. Règle générale OHADA : 12 mois ; un premier exercice
# ou un exercice de transition peut être plus court ou plus long.
# À valider par un expert-comptable guinéen (plafond retenu ici : 24 mois).
MAX_FISCAL_YEAR_MONTHS = 24


@dataclass(frozen=True)
class CompanyData:
    legal_name: str
    legal_form: str
    trade_name: str | None = None
    rccm: str | None = None
    nif: str | None = None
    currency: str = "GNF"
    address: str | None = None
    city: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class TenantLike:
    company_id: uuid.UUID
    user_id: uuid.UUID


def _audit(
    session: Session,
    tenant: TenantLike,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    payload: dict[str, Any],
    ctx: RequestContext,
) -> None:
    record_event(
        session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        actor_user_id=tenant.user_id,
        ip_address=ctx.ip_address,
    )


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _company_snapshot(company: Company) -> dict[str, Any]:
    return {
        "legal_name": company.legal_name,
        "trade_name": company.trade_name,
        "legal_form": company.legal_form,
        "rccm": company.rccm,
        "nif": company.nif,
        "currency": company.currency,
        "address": company.address,
        "city": company.city,
        "phone": company.phone,
        "firm_id": str(company.firm_id) if company.firm_id else None,
    }


# --- Dossiers


def create_company(
    session: Session,
    user: User,
    data: CompanyData,
    *,
    firm_id: uuid.UUID | None,
    first_fiscal_year: tuple[date, date] | None,
    ctx: RequestContext,
) -> Company:
    if firm_id is not None:
        role = session.execute(
            select(FirmMembership.role).where(
                FirmMembership.firm_id == firm_id, FirmMembership.user_id == user.id
            )
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError("Cabinet introuvable.")
        if role != Role.CABINET_ADMIN:
            raise ForbiddenError("Seul un administrateur du cabinet peut créer un dossier client.")

    company = Company(
        legal_name=data.legal_name.strip(),
        trade_name=(data.trade_name or "").strip() or None,
        legal_form=data.legal_form,
        rccm=(data.rccm or "").strip() or None,
        nif=(data.nif or "").strip() or None,
        currency=data.currency,
        address=data.address,
        city=data.city,
        phone=data.phone,
        firm_id=firm_id,
        created_by_user_id=user.id,
    )
    session.add(company)
    session.flush()
    if firm_id is None:
        session.add(
            CompanyMembership(company_id=company.id, user_id=user.id, role=Role.PME_DIRIGEANT)
        )

    bind_tenant(session, company.id)
    tenant = TenantLike(company.id, user.id)
    _audit(
        session,
        tenant,
        action="company.created",
        entity_type="company",
        entity_id=company.id,
        payload=_company_snapshot(company),
        ctx=ctx,
    )

    # Import différé : le module de paramétrage comptable dépend de ce module.
    from kora.accounting.setup import initialize_company  # noqa: PLC0415

    initialize_company(session, company, actor_user_id=user.id, ctx=ctx)
    if first_fiscal_year is not None:
        _insert_fiscal_year(session, tenant, *first_fiscal_year, ctx=ctx)
    session.commit()
    return company


UPDATABLE_FIELDS = (
    "legal_name",
    "trade_name",
    "legal_form",
    "rccm",
    "nif",
    "address",
    "city",
    "phone",
)


def update_company(
    session: Session, tenant: TenantLike, changes: dict[str, Any], ctx: RequestContext
) -> Company:
    """Met à jour la fiche. La devise n'est pas modifiable : elle fixe l'unité de
    toutes les écritures du dossier."""
    company = session.get(Company, tenant.company_id)
    if company is None:
        raise NotFoundError("Dossier introuvable.")
    before = _company_snapshot(company)
    for field, raw in changes.items():
        if field not in UPDATABLE_FIELDS:
            raise BusinessRuleError(f"Le champ « {field} » n'est pas modifiable.")
        value = (raw.strip() or None) if isinstance(raw, str) else raw
        if field in ("legal_name", "legal_form") and value is None:
            raise BusinessRuleError(f"Le champ « {field} » est obligatoire.")
        setattr(company, field, value)
    after = _company_snapshot(company)
    diff = {k: {"avant": before[k], "apres": after[k]} for k in after if before[k] != after[k]}
    if diff:
        _audit(
            session,
            tenant,
            action="company.updated",
            entity_type="company",
            entity_id=company.id,
            payload=diff,
            ctx=ctx,
        )
    session.commit()
    return company


# --- Membres


@dataclass(frozen=True)
class MemberRow:
    membership: CompanyMembership
    user: User


def list_members(session: Session, company_id: uuid.UUID) -> list[MemberRow]:
    rows = session.execute(
        select(CompanyMembership, User)
        .join(User, User.id == CompanyMembership.user_id)
        .where(CompanyMembership.company_id == company_id)
        .order_by(User.full_name)
    ).all()
    return [MemberRow(m, u) for m, u in rows]


def check_company_role(role: str) -> Role:
    if role not in COMPANY_ROLES:
        raise BusinessRuleError("Rôle non attribuable sur un dossier d'entreprise.")
    return Role(role)


def add_member(
    session: Session, tenant: TenantLike, *, email: str, role: str, ctx: RequestContext
) -> MemberRow:
    company_role = check_company_role(role)
    user = get_user_by_email(session, email)
    if user is None:
        raise NotFoundError(
            "Aucun compte Kora n'existe avec cette adresse. Demandez à la personne de "
            "créer son compte, puis réessayez."
        )
    membership = CompanyMembership(company_id=tenant.company_id, user_id=user.id, role=company_role)
    session.add(membership)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Cette personne a déjà accès au dossier.") from exc
    _audit(
        session,
        tenant,
        action="member.added",
        entity_type="membership",
        entity_id=membership.id,
        payload={"user_id": str(user.id), "role": company_role.value},
        ctx=ctx,
    )
    session.commit()
    return MemberRow(membership, user)


def _get_membership(
    session: Session, tenant: TenantLike, membership_id: uuid.UUID
) -> CompanyMembership:
    # Filtre explicite sur le dossier : un identifiant d'un autre dossier est introuvable.
    membership = session.execute(
        select(CompanyMembership)
        .where(
            CompanyMembership.id == membership_id, CompanyMembership.company_id == tenant.company_id
        )
        .with_for_update()
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Membre introuvable.")
    return membership


def _ensure_a_director_remains(
    session: Session, tenant: TenantLike, leaving: CompanyMembership
) -> None:
    company = session.get(Company, tenant.company_id)
    if company is None or company.firm_id is not None or leaving.role != Role.PME_DIRIGEANT:
        return
    directors = session.execute(
        select(func.count())
        .select_from(CompanyMembership)
        .where(
            CompanyMembership.company_id == tenant.company_id,
            CompanyMembership.role == Role.PME_DIRIGEANT,
        )
    ).scalar_one()
    if directors <= 1:
        raise BusinessRuleError("Le dossier doit conserver au moins un dirigeant.")


def change_member_role(
    session: Session, tenant: TenantLike, membership_id: uuid.UUID, role: str, ctx: RequestContext
) -> MemberRow:
    new_role = check_company_role(role)
    membership = _get_membership(session, tenant, membership_id)
    if membership.role != new_role:
        _ensure_a_director_remains(session, tenant, membership)
        _audit(
            session,
            tenant,
            action="member.role_changed",
            entity_type="membership",
            entity_id=membership.id,
            payload={"avant": membership.role, "apres": new_role.value},
            ctx=ctx,
        )
        membership.role = new_role
    session.commit()
    user = session.get(User, membership.user_id)
    assert user is not None  # noqa: S101 (clé étrangère)
    return MemberRow(membership, user)


def remove_member(
    session: Session, tenant: TenantLike, membership_id: uuid.UUID, ctx: RequestContext
) -> None:
    membership = _get_membership(session, tenant, membership_id)
    _ensure_a_director_remains(session, tenant, membership)
    _audit(
        session,
        tenant,
        action="member.removed",
        entity_type="membership",
        entity_id=membership.id,
        payload={"user_id": str(membership.user_id), "role": membership.role},
        ctx=ctx,
    )
    session.delete(membership)
    session.commit()


# --- Exercices


def list_fiscal_years(session: Session, company_id: uuid.UUID) -> list[FiscalYear]:
    return list(
        session.execute(
            select(FiscalYear)
            .where(FiscalYear.tenant_id == company_id)
            .order_by(FiscalYear.start_date.desc())
        ).scalars()
    )


def _insert_fiscal_year(
    session: Session, tenant: TenantLike, start: date, end: date, ctx: RequestContext
) -> FiscalYear:
    if end <= start:
        raise BusinessRuleError("La date de fin doit être postérieure à la date de début.")
    if end >= _add_months(start, MAX_FISCAL_YEAR_MONTHS):
        raise BusinessRuleError(f"Un exercice ne peut pas dépasser {MAX_FISCAL_YEAR_MONTHS} mois.")
    fiscal_year = FiscalYear(tenant_id=tenant.company_id, start_date=start, end_date=end)
    session.add(fiscal_year)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Cet exercice chevauche un exercice existant.") from exc
    _audit(
        session,
        tenant,
        action="fiscal_year.created",
        entity_type="fiscal_year",
        entity_id=fiscal_year.id,
        payload={"debut": start.isoformat(), "fin": end.isoformat()},
        ctx=ctx,
    )
    return fiscal_year


def create_fiscal_year(
    session: Session, tenant: TenantLike, start: date, end: date, ctx: RequestContext
) -> FiscalYear:
    fiscal_year = _insert_fiscal_year(session, tenant, start, end, ctx)
    session.commit()
    return fiscal_year
