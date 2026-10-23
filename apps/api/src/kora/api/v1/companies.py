"""Routes des dossiers d'entreprise : fiche, membres, exercices, journal d'audit."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, Page, RequestBody
from kora.audit.service import verify_chain
from kora.auth.deps import Ctx, CurrentUser, DbSession
from kora.models.audit import AuditEvent
from kora.models.identity import Company, LegalForm
from kora.models.organization import FiscalYear
from kora.organization import service
from kora.organization.service import CompanyData, TenantLike
from kora.tenancy.access import accessible_companies
from kora.tenancy.deps import (
    AuditRead,
    CompanyRead,
    CompanyUpdate,
    FiscalYearsManage,
    FiscalYearsRead,
    MembersManage,
    MembersRead,
    TenantContext,
)
from kora.tenancy.permissions import permissions_for
from kora.tenancy.roles import Role

router = APIRouter(prefix="/companies", tags=["dossiers"])

Text200 = Annotated[str, Field(min_length=1, max_length=200)]
Optional64 = Annotated[str | None, Field(default=None, max_length=64)]


def _actor(tenant: TenantContext) -> TenantLike:
    return TenantLike(tenant.company_id, tenant.user.id)


# --- Schémas


class FiscalYearIn(RequestBody):
    start_date: date
    end_date: date


class CompanyCreate(RequestBody):
    legal_name: Text200
    legal_form: LegalForm
    trade_name: Annotated[str | None, Field(default=None, max_length=200)]
    rccm: Optional64
    nif: Optional64
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "GNF"
    address: Annotated[str | None, Field(default=None, max_length=500)]
    city: Annotated[str | None, Field(default=None, max_length=120)]
    phone: Annotated[str | None, Field(default=None, max_length=32)]
    firm_id: uuid.UUID | None = Field(
        default=None, description="Cabinet gestionnaire (réservé aux administrateurs du cabinet)"
    )
    first_fiscal_year: FiscalYearIn | None = None


class CompanyPatch(RequestBody):
    legal_name: Text200 | None = None
    legal_form: LegalForm | None = None
    trade_name: Annotated[str | None, Field(max_length=200)] = None
    rccm: Optional64 = None
    nif: Optional64 = None
    address: Annotated[str | None, Field(max_length=500)] = None
    city: Annotated[str | None, Field(max_length=120)] = None
    phone: Annotated[str | None, Field(max_length=32)] = None

    @model_validator(mode="after")
    def _not_empty(self) -> "CompanyPatch":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self


class CompanyOut(BaseModel):
    id: uuid.UUID
    legal_name: str
    trade_name: str | None
    legal_form: str
    rccm: str | None
    nif: str | None
    currency: str
    address: str | None
    city: str | None
    phone: str | None
    firm_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def of(cls, company: Company) -> "CompanyOut":
        return cls.model_validate(company, from_attributes=True)


class CompanyAccess(BaseModel):
    company: CompanyOut
    role: Role
    permissions: list[str]


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role

    @classmethod
    def of(cls, row: service.MemberRow) -> "MemberOut":
        return cls(
            id=row.membership.id,
            user_id=row.user.id,
            email=row.user.email,
            full_name=row.user.full_name,
            role=Role(row.membership.role),
        )


class MemberCreate(RequestBody):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    role: Role


class MemberUpdate(RequestBody):
    role: Role


class FiscalYearOut(BaseModel):
    id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    closed_at: datetime | None

    @classmethod
    def of(cls, fiscal_year: FiscalYear) -> "FiscalYearOut":
        return cls.model_validate(fiscal_year, from_attributes=True)


class AuditEventOut(BaseModel):
    seq: int
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, Any]
    hash: str


class AuditVerificationOut(BaseModel):
    ok: bool
    events_checked: int
    broken_at_seq: int | None
    reason: str | None


# --- Dossiers


@router.post("", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_company(body: CompanyCreate, user: CurrentUser, db: DbSession, ctx: Ctx) -> CompanyOut:
    data = CompanyData(**body.model_dump(exclude={"firm_id", "first_fiscal_year"}))
    first_year = (
        (body.first_fiscal_year.start_date, body.first_fiscal_year.end_date)
        if body.first_fiscal_year
        else None
    )
    company = service.create_company(
        db, user, data, firm_id=body.firm_id, first_fiscal_year=first_year, ctx=ctx
    )
    return CompanyOut.of(company)


@router.get("", responses=TENANT_ERRORS)
def list_companies(user: CurrentUser, db: DbSession) -> list[CompanyAccess]:
    return [
        CompanyAccess(
            company=CompanyOut.of(company),
            role=role,
            permissions=sorted(p.value for p in permissions_for(role)),
        )
        for company, role in accessible_companies(db, user)
    ]


@router.get("/{company_id}", responses=TENANT_ERRORS)
def get_company(tenant: CompanyRead, db: DbSession) -> CompanyAccess:
    company = db.get(Company, tenant.company_id)
    assert company is not None  # noqa: S101 (accès résolu juste avant)
    return CompanyAccess(
        company=CompanyOut.of(company),
        role=tenant.role,
        permissions=sorted(p.value for p in tenant.permissions),
    )


@router.patch("/{company_id}", responses=WRITE_ERRORS)
def update_company(
    body: CompanyPatch, tenant: CompanyUpdate, db: DbSession, ctx: Ctx
) -> CompanyOut:
    changes = body.model_dump(exclude_unset=True)
    return CompanyOut.of(service.update_company(db, _actor(tenant), changes, ctx))


# --- Membres


@router.get("/{company_id}/members", responses=TENANT_ERRORS)
def list_members(tenant: MembersRead, db: DbSession) -> list[MemberOut]:
    return [MemberOut.of(row) for row in service.list_members(db, tenant.company_id)]


@router.post("/{company_id}/members", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def add_member(body: MemberCreate, tenant: MembersManage, db: DbSession, ctx: Ctx) -> MemberOut:
    row = service.add_member(db, _actor(tenant), email=body.email, role=body.role, ctx=ctx)
    return MemberOut.of(row)


@router.patch("/{company_id}/members/{membership_id}", responses=WRITE_ERRORS)
def change_member_role(
    membership_id: uuid.UUID,
    body: MemberUpdate,
    tenant: MembersManage,
    db: DbSession,
    ctx: Ctx,
) -> MemberOut:
    return MemberOut.of(
        service.change_member_role(db, _actor(tenant), membership_id, body.role, ctx)
    )


@router.delete(
    "/{company_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
def remove_member(membership_id: uuid.UUID, tenant: MembersManage, db: DbSession, ctx: Ctx) -> None:
    service.remove_member(db, _actor(tenant), membership_id, ctx)


# --- Exercices


@router.get("/{company_id}/fiscal-years", responses=TENANT_ERRORS)
def list_fiscal_years(tenant: FiscalYearsRead, db: DbSession) -> list[FiscalYearOut]:
    return [FiscalYearOut.of(fy) for fy in service.list_fiscal_years(db, tenant.company_id)]


@router.post(
    "/{company_id}/fiscal-years", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS
)
def create_fiscal_year(
    body: FiscalYearIn, tenant: FiscalYearsManage, db: DbSession, ctx: Ctx
) -> FiscalYearOut:
    fiscal_year = service.create_fiscal_year(
        db, _actor(tenant), body.start_date, body.end_date, ctx
    )
    return FiscalYearOut.of(fiscal_year)


# --- Journal d'audit


@router.get("/{company_id}/audit-events", responses=TENANT_ERRORS)
def list_audit_events(
    tenant: AuditRead, db: DbSession, limit: Limit = 50, offset: Offset = 0
) -> Page[AuditEventOut]:
    base = select(AuditEvent).where(AuditEvent.tenant_id == tenant.company_id)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    events = db.execute(base.order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)).scalars()
    return Page(
        items=[AuditEventOut.model_validate(e, from_attributes=True) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{company_id}/audit-events/verification", responses=TENANT_ERRORS)
def verify_audit_chain(tenant: AuditRead, db: DbSession) -> AuditVerificationOut:
    result = verify_chain(db)
    return AuditVerificationOut(
        ok=result.ok,
        events_checked=result.events_checked,
        broken_at_seq=result.broken_at_seq,
        reason=result.reason,
    )
