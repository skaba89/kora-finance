"""Résolution du rôle effectif d'un utilisateur sur un dossier d'entreprise."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.models.identity import (
    Company,
    CompanyMembership,
    FirmAssignment,
    FirmMembership,
    User,
)
from kora.tenancy.roles import Role


def resolve_role(session: Session, user: User, company_id: uuid.UUID) -> Role | None:
    """Rôle de l'utilisateur sur le dossier, ou None s'il n'y a pas accès.

    Ordre : rattachement direct à la PME, puis cabinet gestionnaire du dossier
    (CABINET_ADMIN : tous les dossiers du cabinet ; CABINET_COLLABORATEUR : dossiers
    affectés uniquement).
    """
    direct = session.execute(
        select(CompanyMembership.role).where(
            CompanyMembership.company_id == company_id, CompanyMembership.user_id == user.id
        )
    ).scalar_one_or_none()
    if direct is not None:
        return Role(direct)

    firm_row = session.execute(
        select(FirmMembership.id, FirmMembership.role)
        .join(Company, Company.firm_id == FirmMembership.firm_id)
        .where(Company.id == company_id, FirmMembership.user_id == user.id)
    ).one_or_none()
    if firm_row is None:
        return None
    membership_id, firm_role = firm_row
    if firm_role == Role.CABINET_ADMIN:
        return Role.CABINET_ADMIN
    assigned = session.execute(
        select(FirmAssignment.id).where(
            FirmAssignment.firm_membership_id == membership_id,
            FirmAssignment.company_id == company_id,
        )
    ).scalar_one_or_none()
    return Role.CABINET_COLLABORATEUR if assigned is not None else None


def accessible_companies(session: Session, user: User) -> list[tuple[Company, Role]]:
    """Tous les dossiers accessibles, avec le rôle effectif (sans requête N+1)."""
    direct = session.execute(
        select(Company, CompanyMembership.role)
        .join(CompanyMembership, CompanyMembership.company_id == Company.id)
        .where(CompanyMembership.user_id == user.id)
    ).all()
    via_admin = (
        session.execute(
            select(Company)
            .join(FirmMembership, FirmMembership.firm_id == Company.firm_id)
            .where(FirmMembership.user_id == user.id, FirmMembership.role == Role.CABINET_ADMIN)
        )
        .scalars()
        .all()
    )
    via_assignment = (
        session.execute(
            select(Company)
            .join(FirmAssignment, FirmAssignment.company_id == Company.id)
            .join(FirmMembership, FirmMembership.id == FirmAssignment.firm_membership_id)
            .where(
                FirmMembership.user_id == user.id,
                FirmMembership.role == Role.CABINET_COLLABORATEUR,
                FirmMembership.firm_id == Company.firm_id,
            )
        )
        .scalars()
        .all()
    )

    result: dict[uuid.UUID, tuple[Company, Role]] = {}
    for company in via_assignment:
        result[company.id] = (company, Role.CABINET_COLLABORATEUR)
    for company in via_admin:
        result[company.id] = (company, Role.CABINET_ADMIN)
    for company, role in direct:
        result[company.id] = (company, Role(role))
    return sorted(result.values(), key=lambda item: item[0].legal_name.lower())
