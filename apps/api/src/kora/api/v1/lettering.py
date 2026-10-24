"""Routes du lettrage des comptes de tiers."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from kora.accounting import lettering
from kora.accounting.entries import Actor
from kora.api.v1.common import (
    TENANT_ERRORS,
    WRITE_ERRORS,
    Limit,
    Money,
    Offset,
    RequestBody,
    SignedMoney,
)
from kora.auth.deps import Ctx, DbSession
from kora.tenancy.deps import EntriesRead, LetteringManage, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["lettrage"])


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class LetterableLineOut(BaseModel):
    line_id: uuid.UUID
    entry_id: uuid.UUID
    entry_date: date
    journal_code: str
    number: int | None
    reference: str | None
    label: str
    debit: Money
    credit: Money
    lettering_id: uuid.UUID | None
    lettering_code: str | None


class LetterableLinesOut(BaseModel):
    account_id: uuid.UUID
    account_number: str
    account_label: str
    open_balance: SignedMoney = Field(description="Solde non lettré (positif = débiteur)")
    items: list[LetterableLineOut]
    total: int
    limit: int
    offset: int


class LetteringCreate(RequestBody):
    account_id: uuid.UUID
    line_ids: Annotated[list[uuid.UUID], Field(min_length=2, max_length=500)]


class AutoLetteringIn(RequestBody):
    account_id: uuid.UUID


class LetteringOut(BaseModel):
    id: uuid.UUID
    code: str


class AutoLetteringOut(BaseModel):
    created: int


@router.get("/lettering/lines", responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]})
def list_lines(
    tenant: EntriesRead,
    db: DbSession,
    account_id: uuid.UUID,
    line_status: Annotated[Literal["open", "lettered", "all"], Query(alias="status")] = "open",
    limit: Limit = 100,
    offset: Offset = 0,
) -> LetterableLinesOut:
    """Lignes validées d'un compte de tiers, tous exercices confondus."""
    result = lettering.list_lines(
        db, tenant.company_id, account_id, status=line_status, limit=limit, offset=offset
    )
    return LetterableLinesOut(
        account_id=result.account.id,
        account_number=result.account.number,
        account_label=result.account.label,
        open_balance=result.open_balance,
        items=[LetterableLineOut(**vars(line)) for line in result.lines],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@router.post("/letterings", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_lettering(
    body: LetteringCreate, tenant: LetteringManage, db: DbSession, ctx: Ctx
) -> LetteringOut:
    created = lettering.letter(db, _actor(tenant, ctx), body.account_id, body.line_ids)
    return LetteringOut(id=created.id, code=lettering.lettering_code(created.sequence))


@router.post("/letterings/auto", responses=WRITE_ERRORS)
def auto_lettering(
    body: AutoLetteringIn, tenant: LetteringManage, db: DbSession, ctx: Ctx
) -> AutoLetteringOut:
    """Lettre automatiquement les lignes de même référence de pièce qui s'équilibrent."""
    count = lettering.auto_letter_by_reference(db, _actor(tenant, ctx), body.account_id)
    return AutoLetteringOut(created=count)


@router.delete(
    "/letterings/{lettering_id}", status_code=status.HTTP_204_NO_CONTENT, responses=WRITE_ERRORS
)
def delete_lettering(
    lettering_id: uuid.UUID, tenant: LetteringManage, db: DbSession, ctx: Ctx
) -> None:
    lettering.unletter(db, _actor(tenant, ctx), lettering_id)
