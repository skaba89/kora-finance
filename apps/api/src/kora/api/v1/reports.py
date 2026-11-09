"""États comptables : balance générale et grand livre (écritures validées)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from kora.accounting import reports
from kora.accounting.reports import AccountFilter, BalanceRow
from kora.api.v1.common import TENANT_ERRORS, Limit, Money, Offset, SignedMoney
from kora.auth.deps import DbSession
from kora.db.snapshot import lecture_instantanee
from kora.tenancy.deps import EntriesRead

router = APIRouter(prefix="/companies/{company_id}", tags=["états comptables"])

_ERRORS = {**TENANT_ERRORS, 422: TENANT_ERRORS[404]}


class PeriodOut(BaseModel):
    fiscal_year_id: uuid.UUID
    date_from: date
    date_to: date


class BalanceRowOut(BaseModel):
    account_id: uuid.UUID
    number: str
    label: str
    opening_debit: Money
    opening_credit: Money
    period_debit: Money
    period_credit: Money
    closing_debit: Money
    closing_credit: Money

    @classmethod
    def of(cls, row: BalanceRow) -> "BalanceRowOut":
        return cls(
            account_id=row.account_id,
            number=row.number,
            label=row.label,
            opening_debit=max(row.opening, 0),
            opening_credit=max(-row.opening, 0),
            period_debit=row.period_debit,
            period_credit=row.period_credit,
            closing_debit=max(row.closing, 0),
            closing_credit=max(-row.closing, 0),
        )


class BalanceTotals(BaseModel):
    opening_debit: Money
    opening_credit: Money
    period_debit: Money
    period_credit: Money
    closing_debit: Money
    closing_credit: Money


class TrialBalanceOut(BaseModel):
    period: PeriodOut
    rows: list[BalanceRowOut]
    totals: BalanceTotals
    # Sans objet (null) si la balance est filtrée : seule la balance complète s'équilibre.
    balanced: bool | None


@router.get("/trial-balance", responses=_ERRORS)
def trial_balance(
    tenant: EntriesRead,
    db: DbSession,
    fiscal_year_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    account_class: Annotated[int | None, Query(alias="class", ge=1, le=9)] = None,
    prefix: Annotated[str | None, Query(pattern=r"^[0-9]{1,12}$")] = None,
    include_zero: bool = False,
) -> TrialBalanceOut:
    """Balance à six colonnes : soldes d'ouverture, mouvements de la période, soldes de
    clôture. `balanced` est faux si la balance n'est pas équilibrée (anomalie)."""
    period = reports.resolve_period(db, tenant.company_id, fiscal_year_id, date_from, date_to)
    rows = [
        BalanceRowOut.of(r)
        for r in reports.trial_balance(
            db,
            tenant.company_id,
            period,
            AccountFilter(
                account_class=account_class, number_prefix=prefix, include_zero=include_zero
            ),
        )
    ]
    totals = BalanceTotals(
        opening_debit=sum(r.opening_debit for r in rows),
        opening_credit=sum(r.opening_credit for r in rows),
        period_debit=sum(r.period_debit for r in rows),
        period_credit=sum(r.period_credit for r in rows),
        closing_debit=sum(r.closing_debit for r in rows),
        closing_credit=sum(r.closing_credit for r in rows),
    )
    # L'équilibre n'a de sens que sur la balance complète (sans filtre de comptes).
    filtered = account_class is not None or prefix is not None
    balanced = (
        None
        if filtered
        else (
            totals.opening_debit == totals.opening_credit
            and totals.period_debit == totals.period_credit
            and totals.closing_debit == totals.closing_credit
        )
    )
    return TrialBalanceOut(
        period=PeriodOut(
            fiscal_year_id=period.fiscal_year.id, date_from=period.date_from, date_to=period.date_to
        ),
        rows=rows,
        totals=totals,
        balanced=balanced,
    )


class LedgerAccountOut(BaseModel):
    id: uuid.UUID
    number: str
    label: str


class LedgerLineOut(BaseModel):
    entry_id: uuid.UUID
    entry_date: date
    journal_code: str
    number: int | None
    reference: str | None
    label: str
    debit: Money
    credit: Money
    balance: SignedMoney


class LedgerOut(BaseModel):
    account: LedgerAccountOut
    period: PeriodOut
    opening: SignedMoney
    period_debit: Money
    period_credit: Money
    closing: SignedMoney
    items: list[LedgerLineOut]
    total: int
    limit: int
    offset: int


@router.get("/ledger", responses=_ERRORS)
def ledger(
    tenant: EntriesRead,
    db: DbSession,
    account_id: uuid.UUID,
    fiscal_year_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> LedgerOut:
    """Grand livre d'un compte : solde d'ouverture, mouvements avec solde progressif
    (exact sur chaque page), solde de clôture.

    KF-05 : totaux et lignes sont lus sous le même instantané (REPEATABLE READ) — une
    validation concurrente entre les deux requêtes ne peut plus séparer les uns des
    autres. (La balance générale tient en une seule requête : elle est atomique.)
    """
    period = reports.resolve_period(db, tenant.company_id, fiscal_year_id, date_from, date_to)
    with lecture_instantanee(tenant.company_id) as snap:
        result = reports.account_ledger(
            snap, tenant.company_id, account_id, period, limit=limit, offset=offset
        )
    return LedgerOut(
        account=LedgerAccountOut(
            id=result.account.id, number=result.account.number, label=result.account.label
        ),
        period=PeriodOut(
            fiscal_year_id=period.fiscal_year.id, date_from=period.date_from, date_to=period.date_to
        ),
        opening=result.opening,
        period_debit=result.period_debit,
        period_credit=result.period_credit,
        closing=result.closing,
        items=[LedgerLineOut(**vars(line)) for line in result.lines],
        total=result.total_lines,
        limit=limit,
        offset=offset,
    )
