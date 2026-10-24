"""Routes de verrouillage de période, de clôture et de réouverture d'exercice."""

import uuid
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from kora.accounting import closing
from kora.accounting.entries import Actor
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, RequestBody, SignedMoney
from kora.api.v1.companies import FiscalYearOut
from kora.auth.deps import Ctx, DbSession
from kora.tenancy.deps import FiscalYearsClose, FiscalYearsManage, FiscalYearsRead, TenantContext
from kora.tenancy.permissions import Permission

router = APIRouter(prefix="/companies/{company_id}/fiscal-years/{fiscal_year_id}", tags=["clôture"])


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class LockIn(RequestBody):
    locked_until: date | None = Field(
        description="Dernier jour verrouillé ; null pour tout déverrouiller"
    )


class ClosingCheckOut(BaseModel):
    ready: bool
    issues: list[str]
    drafts: int
    result: SignedMoney = Field(description="Résultat de l'exercice (positif = bénéfice)")
    carried_accounts: int = Field(description="Comptes de bilan reportés en à-nouveaux")
    next_fiscal_year_id: uuid.UUID | None


class ClosingOut(BaseModel):
    fiscal_year: FiscalYearOut
    opening_entry_id: uuid.UUID | None


@router.post("/lock", responses=WRITE_ERRORS)
def lock_period(
    fiscal_year_id: uuid.UUID, body: LockIn, tenant: FiscalYearsManage, db: DbSession, ctx: Ctx
) -> FiscalYearOut:
    """Verrouille la période jusqu'à une date. Reculer la date exige le droit de clôture."""
    year = closing.lock_period(
        db,
        _actor(tenant, ctx),
        fiscal_year_id,
        body.locked_until,
        can_unlock=Permission.FISCAL_YEARS_CLOSE in tenant.permissions,
    )
    return FiscalYearOut.of(year)


@router.get("/closing-check", responses=TENANT_ERRORS)
def closing_check(
    fiscal_year_id: uuid.UUID, tenant: FiscalYearsRead, db: DbSession
) -> ClosingCheckOut:
    """Ce que ferait la clôture, et ce qui l'empêche, sans rien modifier."""
    plan = closing.plan_closing(db, tenant.company_id, fiscal_year_id)
    return ClosingCheckOut(
        ready=plan.ready,
        issues=plan.issues,
        drafts=plan.drafts,
        result=plan.result,
        carried_accounts=len(plan.lines),
        next_fiscal_year_id=plan.next_year.id if plan.next_year else None,
    )


@router.post("/closing", responses=WRITE_ERRORS)
def close_fiscal_year(
    fiscal_year_id: uuid.UUID, tenant: FiscalYearsClose, db: DbSession, ctx: Ctx
) -> ClosingOut:
    """Clôture l'exercice et génère les à-nouveaux dans l'exercice suivant."""
    year, entry_id = closing.close(db, _actor(tenant, ctx), fiscal_year_id)
    return ClosingOut(fiscal_year=FiscalYearOut.of(year), opening_entry_id=entry_id)


@router.post("/reopening", responses=WRITE_ERRORS)
def reopen_fiscal_year(
    fiscal_year_id: uuid.UUID, tenant: FiscalYearsClose, db: DbSession, ctx: Ctx
) -> FiscalYearOut:
    """Rouvre l'exercice ; ses à-nouveaux générés sont contre-passés."""
    return FiscalYearOut.of(closing.reopen(db, _actor(tenant, ctx), fiscal_year_id))
