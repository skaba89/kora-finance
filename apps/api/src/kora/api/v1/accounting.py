"""Routes du paramétrage comptable : plan de comptes et taux de taxes."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from kora.accounting import service
from kora.accounting.service import Actor, TaxRateData
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, Page, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.models.accounting import Account, TaxRate
from kora.tenancy.deps import (
    AccountsManage,
    AccountsRead,
    TaxesManage,
    TaxesRead,
    TenantContext,
)

router = APIRouter(prefix="/companies/{company_id}", tags=["paramétrage comptable"])

AccountNumber = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,11}$")]


def _actor(tenant: TenantContext) -> Actor:
    return Actor(tenant.company_id, tenant.user.id)


class AccountOut(BaseModel):
    id: uuid.UUID
    number: str
    label: str
    reference: str | None
    is_active: bool

    @classmethod
    def of(cls, account: Account) -> "AccountOut":
        return cls.model_validate(account, from_attributes=True)


class AccountCreate(RequestBody):
    number: AccountNumber
    label: Annotated[str, Field(min_length=1, max_length=200)]


class AccountUpdate(RequestBody):
    label: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    is_active: bool | None = None


class TaxRateOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    kind: str
    rate_basis_points: int = Field(description="Taux en points de base : 1800 = 18,00 %")
    valid_from: date
    valid_to: date | None
    collected_account_number: str | None
    deductible_account_number: str | None
    verified_at: datetime | None
    note: str | None

    @classmethod
    def of(cls, rate: TaxRate) -> "TaxRateOut":
        return cls.model_validate(rate, from_attributes=True)


class TaxRateCreate(RequestBody):
    code: Annotated[str, Field(pattern=r"^[A-Z0-9_]{2,40}$")]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Literal["TVA", "AUTRE"]
    rate_basis_points: Annotated[int, Field(ge=0, le=10000)]
    valid_from: date
    collected_account_number: AccountNumber | None = None
    deductible_account_number: AccountNumber | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None


@router.get("/accounts", responses=TENANT_ERRORS)
def list_accounts(
    tenant: AccountsRead,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100, description="Numéro ou libellé")] = None,
    account_class: Annotated[int | None, Query(alias="class", ge=1, le=8)] = None,
    active_only: bool = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[AccountOut]:
    items, total = service.list_accounts(
        db,
        tenant.company_id,
        search=q,
        account_class=account_class,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return Page(items=[AccountOut.of(a) for a in items], total=total, limit=limit, offset=offset)


@router.post("/accounts", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_account(
    body: AccountCreate, tenant: AccountsManage, db: DbSession, ctx: Ctx
) -> AccountOut:
    account = service.create_account(
        db, _actor(tenant), number=body.number, label=body.label, ctx=ctx
    )
    return AccountOut.of(account)


@router.patch("/accounts/{account_id}", responses=WRITE_ERRORS)
def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    tenant: AccountsManage,
    db: DbSession,
    ctx: Ctx,
) -> AccountOut:
    account = service.update_account(
        db, _actor(tenant), account_id, label=body.label, is_active=body.is_active, ctx=ctx
    )
    return AccountOut.of(account)


@router.get("/tax-rates", responses=TENANT_ERRORS)
def list_tax_rates(tenant: TaxesRead, db: DbSession) -> list[TaxRateOut]:
    return [TaxRateOut.of(r) for r in service.list_tax_rates(db, tenant.company_id)]


@router.post("/tax-rates", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def add_tax_rate(body: TaxRateCreate, tenant: TaxesManage, db: DbSession, ctx: Ctx) -> TaxRateOut:
    rate = service.add_tax_rate_version(db, _actor(tenant), TaxRateData(**body.model_dump()), ctx)
    return TaxRateOut.of(rate)


@router.post("/tax-rates/{tax_rate_id}/verification", responses=WRITE_ERRORS)
def verify_tax_rate(
    tax_rate_id: uuid.UUID, tenant: TaxesManage, db: DbSession, ctx: Ctx
) -> TaxRateOut:
    return TaxRateOut.of(service.verify_tax_rate(db, _actor(tenant), tax_rate_id, ctx))
