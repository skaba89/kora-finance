"""Cas d'usage : cabinets comptables, collaborateurs et affectations aux dossiers.

Le tableau de bord de portefeuille arrive en phase 8 ; ici, le minimum pour que les
rôles CABINET_ADMIN et CABINET_COLLABORATEUR soient réellement opérants.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth.service import RequestContext, get_user_by_email
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.identity import Company, Firm, FirmAssignment, FirmMembership, User
from kora.tenancy.roles import FIRM_ROLES, Role


@dataclass(frozen=True)
class FirmRow:
    firm: Firm
    role: Role


@dataclass(frozen=True)
class FirmMemberRow:
    membership: FirmMembership
    user: User


def _platform_audit(
    session: Session,
    user: User,
    *,
    action: str,
    entity_id: uuid.UUID,
    payload: dict[str, str],
    ctx: RequestContext,
) -> None:
    bind_tenant(session, None)
    record_event(
        session,
        action=action,
        entity_type="firm",
        entity_id=entity_id,
        payload=payload,
        actor_user_id=user.id,
        ip_address=ctx.ip_address,
    )


def create_firm(session: Session, user: User, name: str, ctx: RequestContext) -> Firm:
    firm = Firm(name=name.strip())
    session.add(firm)
    session.flush()
    session.add(FirmMembership(firm_id=firm.id, user_id=user.id, role=Role.CABINET_ADMIN))
    _platform_audit(
        session, user, action="firm.created", entity_id=firm.id, payload={"nom": firm.name}, ctx=ctx
    )
    session.commit()
    return firm


def list_firms(session: Session, user: User) -> list[FirmRow]:
    rows = session.execute(
        select(Firm, FirmMembership.role)
        .join(FirmMembership, FirmMembership.firm_id == Firm.id)
        .where(FirmMembership.user_id == user.id)
        .order_by(Firm.name)
    ).all()
    return [FirmRow(firm, Role(role)) for firm, role in rows]


def list_firm_members(session: Session, user: User, firm_id: uuid.UUID) -> list[FirmMemberRow]:
    """Liste les membres d'un cabinet, lecture réservée aux administrateurs.

    L'écran d'affectation a besoin du courriel et du nom complet pour proposer
    les collaborateurs ; l'ajout et l'affectation restent les seules écritures.
    """
    firm = _require_firm_admin(session, user, firm_id)
    rows = session.execute(
        select(FirmMembership, User)
        .join(User, User.id == FirmMembership.user_id)
        .where(FirmMembership.firm_id == firm.id)
        # Administrateurs d'abord, puis collaborateurs par nom : ordre stable.
        .order_by(FirmMembership.role, User.full_name, User.email)
    ).all()
    return [FirmMemberRow(membership, member) for membership, member in rows]


def list_firm_portfolio(session: Session, user: User, firm_id: uuid.UUID) -> list[Company]:
    """Dossiers du cabinet visibles selon le rôle, sans détail comptable.

    Administrateur : tous les dossiers du cabinet. Collaborateur : seulement
    ceux dont l'affectation est active. Non-membre : 404, sans divulgation.
    """
    membership = session.execute(
        select(FirmMembership).where(
            FirmMembership.firm_id == firm_id, FirmMembership.user_id == user.id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Cabinet introuvable.")
    if membership.role == Role.CABINET_ADMIN:
        query = select(Company).where(Company.firm_id == firm_id)
    else:
        query = (
            select(Company)
            .join(FirmAssignment, FirmAssignment.company_id == Company.id)
            .where(
                Company.firm_id == firm_id,
                FirmAssignment.firm_membership_id == membership.id,
            )
        )
    return list(session.scalars(query.order_by(Company.legal_name, Company.id)).all())


def _require_firm_admin(session: Session, user: User, firm_id: uuid.UUID) -> Firm:
    role = session.execute(
        select(FirmMembership.role).where(
            FirmMembership.firm_id == firm_id, FirmMembership.user_id == user.id
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Cabinet introuvable.")
    if role != Role.CABINET_ADMIN:
        raise ForbiddenError("Action réservée aux administrateurs du cabinet.")
    firm = session.get(Firm, firm_id)
    assert firm is not None  # noqa: S101 (clé étrangère)
    return firm


def add_firm_member(
    session: Session, user: User, firm_id: uuid.UUID, *, email: str, role: str, ctx: RequestContext
) -> FirmMembership:
    firm = _require_firm_admin(session, user, firm_id)
    if role not in FIRM_ROLES:
        raise BusinessRuleError("Rôle non attribuable dans un cabinet.")
    member = get_user_by_email(session, email)
    if member is None:
        raise NotFoundError(
            "Aucun compte Kora n'existe avec cette adresse. Demandez à la personne de "
            "créer son compte, puis réessayez."
        )
    membership = FirmMembership(firm_id=firm.id, user_id=member.id, role=role)
    session.add(membership)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Cette personne fait déjà partie du cabinet.") from exc
    _platform_audit(
        session,
        user,
        action="firm.member_added",
        entity_id=firm.id,
        payload={"user_id": str(member.id), "role": role},
        ctx=ctx,
    )
    session.commit()
    return membership


def assign_collaborator(
    session: Session,
    user: User,
    firm_id: uuid.UUID,
    *,
    firm_membership_id: uuid.UUID,
    company_id: uuid.UUID,
    ctx: RequestContext,
) -> FirmAssignment:
    firm = _require_firm_admin(session, user, firm_id)
    membership = session.execute(
        select(FirmMembership).where(
            FirmMembership.id == firm_membership_id, FirmMembership.firm_id == firm.id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Collaborateur introuvable dans ce cabinet.")
    if membership.role != Role.CABINET_COLLABORATEUR:
        raise BusinessRuleError(
            "Seuls les collaborateurs sont affectés : un administrateur voit déjà "
            "tous les dossiers."
        )
    company = session.execute(
        select(Company).where(Company.id == company_id, Company.firm_id == firm.id)
    ).scalar_one_or_none()
    if company is None:
        raise NotFoundError("Dossier introuvable dans ce cabinet.")
    assignment = FirmAssignment(firm_membership_id=membership.id, company_id=company.id)
    session.add(assignment)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Ce collaborateur est déjà affecté à ce dossier.") from exc
    # L'affectation ouvre un accès au dossier : elle est tracée dans sa propre chaîne.
    bind_tenant(session, company.id)
    record_event(
        session,
        action="firm.collaborator_assigned",
        entity_type="firm_assignment",
        entity_id=assignment.id,
        payload={"user_id": str(membership.user_id)},
        actor_user_id=user.id,
        ip_address=ctx.ip_address,
    )
    session.commit()
    return assignment
