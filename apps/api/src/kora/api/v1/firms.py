"""Routes des cabinets comptables (minimum de la phase 1 ; portefeuille en phase 8)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from kora.api.v1.common import WRITE_ERRORS, RequestBody
from kora.auth.deps import Ctx, CurrentUser, DbSession
from kora.organization import firms
from kora.tenancy.roles import Role

router = APIRouter(prefix="/firms", tags=["cabinets"])


class FirmCreate(RequestBody):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class FirmOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    created_at: datetime


class FirmMemberCreate(RequestBody):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    role: Role


class FirmMemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: Role


class FirmMemberDetail(BaseModel):
    """Membre de cabinet avec les coordonnées utiles à l'écran d'affectation."""

    id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    email: str
    full_name: str


class FirmPortfolioCompany(BaseModel):
    """Fiche synthétique d'un dossier client, sans donnée financière."""

    id: uuid.UUID
    legal_name: str
    trade_name: str | None
    city: str | None
    currency: str


class AssignmentCreate(RequestBody):
    firm_membership_id: uuid.UUID
    company_id: uuid.UUID


class AssignmentOut(BaseModel):
    id: uuid.UUID
    firm_membership_id: uuid.UUID
    company_id: uuid.UUID


@router.post("", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_firm(body: FirmCreate, user: CurrentUser, db: DbSession, ctx: Ctx) -> FirmOut:
    firm = firms.create_firm(db, user, body.name, ctx)
    return FirmOut(id=firm.id, name=firm.name, role=Role.CABINET_ADMIN, created_at=firm.created_at)


@router.get("", responses=WRITE_ERRORS)
def list_firms(user: CurrentUser, db: DbSession) -> list[FirmOut]:
    return [
        FirmOut(id=r.firm.id, name=r.firm.name, role=r.role, created_at=r.firm.created_at)
        for r in firms.list_firms(db, user)
    ]


@router.get("/{firm_id}/members", responses=WRITE_ERRORS)
def list_firm_members(
    firm_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[FirmMemberDetail]:
    return [
        FirmMemberDetail(
            id=r.membership.id,
            user_id=r.membership.user_id,
            role=Role(r.membership.role),
            email=r.user.email,
            full_name=r.user.full_name,
        )
        for r in firms.list_firm_members(db, user, firm_id)
    ]


@router.get("/{firm_id}/portfolio", responses=WRITE_ERRORS)
def list_firm_portfolio(
    firm_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[FirmPortfolioCompany]:
    return [
        FirmPortfolioCompany(
            id=company.id,
            legal_name=company.legal_name,
            trade_name=company.trade_name,
            city=company.city,
            currency=company.currency,
        )
        for company in firms.list_firm_portfolio(db, user, firm_id)
    ]


@router.post("/{firm_id}/members", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def add_firm_member(
    firm_id: uuid.UUID, body: FirmMemberCreate, user: CurrentUser, db: DbSession, ctx: Ctx
) -> FirmMemberOut:
    membership = firms.add_firm_member(db, user, firm_id, email=body.email, role=body.role, ctx=ctx)
    return FirmMemberOut(id=membership.id, user_id=membership.user_id, role=Role(membership.role))


@router.post("/{firm_id}/assignments", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def assign_collaborator(
    firm_id: uuid.UUID, body: AssignmentCreate, user: CurrentUser, db: DbSession, ctx: Ctx
) -> AssignmentOut:
    assignment = firms.assign_collaborator(
        db,
        user,
        firm_id,
        firm_membership_id=body.firm_membership_id,
        company_id=body.company_id,
        ctx=ctx,
    )
    return AssignmentOut(
        id=assignment.id,
        firm_membership_id=assignment.firm_membership_id,
        company_id=assignment.company_id,
    )


@router.delete(
    "/{firm_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
def revoke_firm_collaborator(
    firm_id: uuid.UUID,
    membership_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    ctx: Ctx,
) -> None:
    firms.revoke_firm_collaborator(db, user, firm_id, membership_id, ctx)
