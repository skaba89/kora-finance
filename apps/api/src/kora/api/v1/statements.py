"""Route des états financiers : bilan et compte de résultat (exercice N et N-1)."""

import uuid
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from kora.accounting import reports, statements
from kora.accounting.statements import Statements
from kora.api.v1.common import TENANT_ERRORS, SignedMoney
from kora.auth.deps import DbSession
from kora.db.snapshot import lecture_instantanee
from kora.tenancy.deps import EntriesRead

router = APIRouter(prefix="/companies/{company_id}", tags=["états financiers"])


class AssetLineOut(BaseModel):
    code: str
    label: str
    is_total: bool
    gross: SignedMoney
    depreciation: SignedMoney
    net: SignedMoney
    previous_net: SignedMoney | None


class StatementLineOut(BaseModel):
    code: str
    label: str
    is_total: bool
    amount: SignedMoney
    previous_amount: SignedMoney | None


class PeriodRef(BaseModel):
    fiscal_year_id: uuid.UUID
    start_date: date
    date_to: date


class FinancialStatementsOut(BaseModel):
    reference: str = Field(description="Version du référentiel d'affectation des comptes")
    period: PeriodRef
    previous_period: PeriodRef | None
    assets: list[AssetLineOut]
    liabilities: list[StatementLineOut]
    income_statement: list[StatementLineOut]
    net_result: SignedMoney
    balanced: bool = Field(description="Total actif = total passif et tous les comptes affectés")
    unmapped_accounts: list[str]


def _period(result: Statements) -> PeriodRef:
    return PeriodRef(
        fiscal_year_id=result.fiscal_year.id,
        start_date=result.fiscal_year.start_date,
        date_to=result.date_to,
    )


@router.get("/financial-statements", responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]})
def financial_statements(
    tenant: EntriesRead, db: DbSession, fiscal_year_id: uuid.UUID, date_to: date | None = None
) -> FinancialStatementsOut:
    """Bilan et compte de résultat SYSCOHADA révisé sur les écritures validées, avec
    l'exercice précédent en comparaison (s'il existe dans Kora).

    KF-05 : exercices N et N-1 calculés sous le même instantané (REPEATABLE READ).
    """
    period = reports.resolve_period(db, tenant.company_id, fiscal_year_id, None, date_to)
    with lecture_instantanee(tenant.company_id) as snap:
        current = statements.compute(snap, tenant.company_id, period.fiscal_year, period.date_to)
        before = statements.previous_year(snap, tenant.company_id, period.fiscal_year)
        previous = statements.compute(snap, tenant.company_id, before) if before else None

    def prev(code: str) -> int | None:
        return previous.amount(code) if previous else None

    lines = statements.template()
    return FinancialStatementsOut(
        reference=statements.REFERENCE,
        period=_period(current),
        previous_period=_period(previous) if previous else None,
        assets=[
            AssetLineOut(
                code=line.code,
                label=line.label,
                is_total=line.kind == "total",
                gross=current.values[line.code].gross,
                depreciation=current.values[line.code].depreciation,
                net=current.values[line.code].net,
                previous_net=prev(line.code),
            )
            for line in lines
            if line.statement == "ACTIF"
        ],
        liabilities=[
            StatementLineOut(
                code=line.code,
                label=line.label,
                is_total=line.kind == "total",
                amount=current.amount(line.code),
                previous_amount=prev(line.code),
            )
            for line in lines
            if line.statement == "PASSIF"
        ],
        income_statement=[
            StatementLineOut(
                code=line.code,
                label=line.label,
                is_total=line.kind == "total",
                amount=current.amount(line.code),
                previous_amount=prev(line.code),
            )
            for line in lines
            if line.statement == "RESULTAT"
        ],
        net_result=current.net_result,
        balanced=current.balanced,
        unmapped_accounts=current.unmapped,
    )
