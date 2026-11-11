"""Routes de la trésorerie : comptes financiers et mouvements (sous-phase 3A)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

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
from kora.tenancy.deps import TenantContext, TreasuryManage, TreasuryRead
from kora.treasury import service
from kora.treasury.service import AccountData, MovementData, TransferData

router = APIRouter(prefix="/companies/{company_id}", tags=["trésorerie"])

ACCOUNT_KINDS = Literal["BANQUE", "CAISSE", "MOBILE_MONEY"]
MOVEMENT_KINDS = Literal["DEPOT", "RETRAIT", "FRAIS"]


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class FinancialAccountOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: ACCOUNT_KINDS
    operator: str | None
    account_number_masked: str | None
    gl_account_id: uuid.UUID
    gl_account_number: str
    gl_account_label: str
    is_active: bool
    balance: SignedMoney = Field(description="Solde du compte comptable lié (positif = débiteur)")
    created_at: str


class FinancialAccountsOut(BaseModel):
    items: list[FinancialAccountOut]


class FinancialAccountCreate(RequestBody):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    kind: ACCOUNT_KINDS
    gl_account_id: uuid.UUID
    operator: Annotated[str | None, Field(pattern=r"^[A-Z0-9_]{2,24}$")] = None
    account_number_masked: Annotated[str | None, Field(max_length=40)] = None


class FinancialMovementOut(BaseModel):
    id: uuid.UUID
    kind: Literal["DEPOT", "RETRAIT", "VIREMENT_INTERNE", "FRAIS"]
    direction: Literal["DEBIT", "CREDIT"]
    amount: Money
    movement_date: date
    label: str
    counterpart_number: str | None
    counterpart_label: str | None
    entry_id: uuid.UUID
    entry_number: int | None
    created_at: str


class FinancialMovementsOut(BaseModel):
    account_id: uuid.UUID
    balance: SignedMoney
    items: list[FinancialMovementOut]
    total: int
    limit: int
    offset: int


class FinancialMovementCreate(RequestBody):
    kind: MOVEMENT_KINDS
    amount: Money
    movement_date: date
    label: Annotated[str, Field(min_length=1, max_length=200)]
    counterpart_account_id: uuid.UUID
    reference: Annotated[str | None, Field(max_length=60)] = None


class FinancialMovementRecorded(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID


class TransferCreate(RequestBody):
    source_account_id: uuid.UUID
    target_account_id: uuid.UUID
    amount: Money
    movement_date: date
    label: Annotated[str, Field(min_length=1, max_length=200)]
    reference: Annotated[str | None, Field(max_length=60)] = None


class TransferRecorded(BaseModel):
    entry_id: uuid.UUID
    source_movement_id: uuid.UUID
    target_movement_id: uuid.UUID


@router.get("/treasury/accounts", responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]})
def list_accounts(tenant: TreasuryRead, db: DbSession) -> FinancialAccountsOut:
    """Comptes financiers du dossier (banques, caisses, Mobile Money) et leurs soldes."""
    return FinancialAccountsOut(
        items=[
            FinancialAccountOut(
                id=view.account.id,
                name=view.account.name,
                kind=view.account.kind,
                operator=view.account.operator,
                account_number_masked=view.account.account_number_masked,
                gl_account_id=view.account.gl_account_id,
                gl_account_number=view.gl_account_number,
                gl_account_label=view.gl_account_label,
                is_active=view.account.is_active,
                balance=view.balance,
                created_at=view.account.created_at.isoformat(),
            )
            for view in service.list_accounts(db, tenant.company_id)
        ]
    )


@router.post("/treasury/accounts", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_account(
    body: FinancialAccountCreate, tenant: TreasuryManage, db: DbSession, ctx: Ctx
) -> FinancialAccountOut:
    created = service.create_account(
        db,
        _actor(tenant, ctx),
        AccountData(
            name=body.name,
            kind=body.kind,
            gl_account_id=body.gl_account_id,
            operator=body.operator,
            account_number_masked=body.account_number_masked,
        ),
    )
    view = service.get_account(db, tenant.company_id, created.id)
    return FinancialAccountOut(
        id=view.account.id,
        name=view.account.name,
        kind=view.account.kind,
        operator=view.account.operator,
        account_number_masked=view.account.account_number_masked,
        gl_account_id=view.account.gl_account_id,
        gl_account_number=view.gl_account_number,
        gl_account_label=view.gl_account_label,
        is_active=view.account.is_active,
        balance=view.balance,
        created_at=view.account.created_at.isoformat(),
    )


@router.get(
    "/treasury/accounts/{account_id}/movements",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def list_movements(
    account_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
    limit: Limit = 100,
    offset: Offset = 0,
) -> FinancialMovementsOut:
    """Historique des mouvements du compte, du plus ancien au plus récent."""
    page = service.list_movements(db, tenant.company_id, account_id, limit=limit, offset=offset)
    return FinancialMovementsOut(
        account_id=page.account.id,
        balance=page.balance,
        items=[
            FinancialMovementOut(
                id=row.id,
                kind=row.kind,
                direction=row.direction,
                amount=row.amount,
                movement_date=row.movement_date,
                label=row.label,
                counterpart_number=row.counterpart_number,
                counterpart_label=row.counterpart_label,
                entry_id=row.entry_id,
                entry_number=row.entry_number,
                created_at=row.created_at,
            )
            for row in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/treasury/accounts/{account_id}/movements",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
def record_movement(
    account_id: uuid.UUID,
    body: FinancialMovementCreate,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> FinancialMovementRecorded:
    """Dépôt, retrait ou frais bancaires : crée l'écriture validée et sa trace."""
    movement = service.record_movement(
        db,
        _actor(tenant, ctx),
        account_id,
        MovementData(
            kind=body.kind,
            amount=body.amount,
            movement_date=body.movement_date,
            label=body.label,
            counterpart_account_id=body.counterpart_account_id,
            reference=body.reference,
        ),
    )
    return FinancialMovementRecorded(id=movement.id, entry_id=movement.entry_id)


@router.post("/treasury/transfers", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def record_transfer(
    body: TransferCreate, tenant: TreasuryManage, db: DbSession, ctx: Ctx
) -> TransferRecorded:
    """Virement interne entre deux comptes financiers du dossier."""
    source, target = service.record_transfer(
        db,
        _actor(tenant, ctx),
        body.source_account_id,
        body.target_account_id,
        TransferData(
            amount=body.amount,
            movement_date=body.movement_date,
            label=body.label,
            reference=body.reference,
        ),
    )
    return TransferRecorded(
        entry_id=source.entry_id,
        source_movement_id=source.id,
        target_movement_id=target.id,
    )
