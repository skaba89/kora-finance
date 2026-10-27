"""Tableau de bord d'un dossier (indicateurs sur les écritures validées)."""

import uuid
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from kora.accounting import dashboard as service
from kora.api.v1.common import TENANT_ERRORS, SignedMoney
from kora.auth.deps import DbSession
from kora.models.common import utcnow
from kora.tenancy.deps import EntriesRead

router = APIRouter(prefix="/companies/{company_id}", tags=["tableau de bord"])


class DashboardFiscalYear(BaseModel):
    id: uuid.UUID
    start_date: date
    end_date: date
    status: str


class TreasuryAccountOut(BaseModel):
    account_id: uuid.UUID
    number: str
    label: str
    balance: SignedMoney


class FiguresOut(BaseModel):
    revenue: SignedMoney
    income: SignedMoney
    expenses: SignedMoney
    result: SignedMoney

    @classmethod
    def of(cls, figures: service.Figures) -> "FiguresOut":
        return cls(
            revenue=figures.revenue,
            income=figures.income,
            expenses=figures.expenses,
            result=figures.result,
        )


class MonthOut(BaseModel):
    month: date
    revenue: SignedMoney
    expenses: SignedMoney


class DashboardOut(BaseModel):
    as_of: date
    fiscal_year: DashboardFiscalYear | None
    treasury: list[TreasuryAccountOut]
    treasury_total: SignedMoney
    receivables: SignedMoney
    payables: SignedMoney
    month: FiguresOut
    year_to_date: FiguresOut
    monthly: list[MonthOut]
    drafts: int


@router.get("/dashboard", responses=TENANT_ERRORS)
def get_dashboard(tenant: EntriesRead, db: DbSession, on: date | None = None) -> DashboardOut:
    """Indicateurs à la date `on` (aujourd'hui par défaut) dans l'exercice qui la couvre :
    trésorerie par compte, chiffre d'affaires, charges et résultat provisoire du mois et
    de l'exercice, clients et fournisseurs, évolution mensuelle, brouillons à valider."""
    data = service.compute(db, tenant.company_id, on or utcnow().date())
    fy = data.fiscal_year
    return DashboardOut(
        as_of=data.as_of,
        fiscal_year=(
            DashboardFiscalYear(
                id=fy.id, start_date=fy.start_date, end_date=fy.end_date, status=fy.status
            )
            if fy
            else None
        ),
        treasury=[
            TreasuryAccountOut(
                account_id=a.account_id, number=a.number, label=a.label, balance=a.balance
            )
            for a in data.treasury
        ],
        treasury_total=data.treasury_total,
        receivables=data.receivables,
        payables=data.payables,
        month=FiguresOut.of(data.month),
        year_to_date=FiguresOut.of(data.year_to_date),
        monthly=[
            MonthOut(month=m.month, revenue=m.revenue, expenses=m.expenses) for m in data.monthly
        ],
        drafts=data.drafts,
    )
