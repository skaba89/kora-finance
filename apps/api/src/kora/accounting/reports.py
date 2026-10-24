"""Balance générale et grand livre, calculés en SQL sur les écritures **validées**.

Les brouillons n'apparaissent dans aucun état : ils ne sont pas encore des écritures
comptables. Tous les montants sont des entiers (unités mineures) ; les sommes sont
faites par PostgreSQL (NUMERIC), sans aucun flottant.

Période : à l'intérieur d'un exercice. Le solde d'ouverture d'un compte comprend les
à-nouveaux (journal de type A_NOUVEAUX, quelle que soit la période demandée) et les
mouvements de l'exercice antérieurs au début de la période.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Numeric, Subquery, case, func, literal, select
from sqlalchemy.orm import Session

from kora.core.errors import BusinessRuleError, NotFoundError
from kora.models.accounting import Account
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalKind, JournalLine
from kora.models.organization import FiscalYear


@dataclass(frozen=True)
class Period:
    fiscal_year: FiscalYear
    date_from: date
    date_to: date


def resolve_period(
    session: Session,
    company_id: uuid.UUID,
    fiscal_year_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
) -> Period:
    fiscal_year = session.execute(
        select(FiscalYear).where(
            FiscalYear.id == fiscal_year_id, FiscalYear.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if fiscal_year is None:
        raise NotFoundError("Exercice introuvable.")
    start = date_from or fiscal_year.start_date
    end = date_to or fiscal_year.end_date
    if start < fiscal_year.start_date or end > fiscal_year.end_date:
        raise BusinessRuleError("La période doit être comprise dans l'exercice.")
    if end < start:
        raise BusinessRuleError("La date de fin précède la date de début.")
    return Period(fiscal_year, start, end)


def _posted_lines(
    company_id: uuid.UUID, fiscal_year_id: uuid.UUID, date_from: date, until: date
) -> Subquery:
    """Lignes validées de l'exercice jusqu'à `until` inclus ; `opening` vrai pour les
    lignes qui forment le solde d'ouverture de la période."""
    return (
        select(
            JournalLine.account_id,
            JournalLine.debit,
            JournalLine.credit,
            (
                (JournalEntry.entry_date < date_from) | (Journal.kind == JournalKind.A_NOUVEAUX)
            ).label("opening"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.tenant_id == company_id,
            JournalEntry.fiscal_year_id == fiscal_year_id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date <= until,
        )
        .subquery()
    )


# --- Balance


@dataclass(frozen=True)
class BalanceRow:
    account_id: uuid.UUID
    number: str
    label: str
    opening_debit: int
    opening_credit: int
    period_debit: int
    period_credit: int

    @property
    def opening(self) -> int:
        """Solde d'ouverture signé : positif = débiteur."""
        return self.opening_debit - self.opening_credit

    @property
    def closing(self) -> int:
        return self.opening + self.period_debit - self.period_credit


@dataclass(frozen=True)
class AccountFilter:
    account_class: int | None = None
    number_prefix: str | None = None
    include_zero: bool = False


def trial_balance(
    session: Session, company_id: uuid.UUID, period: Period, filters: AccountFilter
) -> list[BalanceRow]:
    lines = _posted_lines(company_id, period.fiscal_year.id, period.date_from, period.date_to)
    before = lines.c.opening
    zero = literal(0)
    query = (
        select(
            Account.id,
            Account.number,
            Account.label,
            func.coalesce(func.sum(case((before, lines.c.debit), else_=zero)), 0),
            func.coalesce(func.sum(case((before, lines.c.credit), else_=zero)), 0),
            func.coalesce(func.sum(case((before, zero), else_=lines.c.debit)), 0),
            func.coalesce(func.sum(case((before, zero), else_=lines.c.credit)), 0),
        )
        .select_from(Account)
        .outerjoin(lines, lines.c.account_id == Account.id)
        .where(Account.tenant_id == company_id)
        .group_by(Account.id, Account.number, Account.label)
        .order_by(Account.number)
    )
    if filters.account_class is not None:
        query = query.where(Account.number.startswith(str(filters.account_class)))
    if filters.number_prefix:
        query = query.where(Account.number.startswith(filters.number_prefix))
    if not filters.include_zero:
        query = query.having(func.count(lines.c.account_id) > 0)
    return [
        BalanceRow(account_id, number, label, int(od), int(oc), int(pd), int(pc))
        for account_id, number, label, od, oc, pd, pc in session.execute(query).all()
    ]


# --- Grand livre


@dataclass(frozen=True)
class LedgerLine:
    entry_id: uuid.UUID
    entry_date: date
    journal_code: str
    number: int | None
    reference: str | None
    label: str
    debit: int
    credit: int
    balance: int


@dataclass(frozen=True)
class AccountLedger:
    account: Account
    opening: int
    period_debit: int
    period_credit: int
    lines: list[LedgerLine]
    total_lines: int

    @property
    def closing(self) -> int:
        return self.opening + self.period_debit - self.period_credit


def account_ledger(
    session: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    period: Period,
    *,
    limit: int,
    offset: int,
) -> AccountLedger:
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.tenant_id == company_id)
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte introuvable.")
    lines = _posted_lines(company_id, period.fiscal_year.id, period.date_from, period.date_to)
    before = lines.c.opening
    opening, period_debit, period_credit, count = session.execute(
        select(
            func.coalesce(func.sum(case((before, lines.c.debit - lines.c.credit), else_=0)), 0),
            func.coalesce(func.sum(case((before, 0), else_=lines.c.debit)), 0),
            func.coalesce(func.sum(case((before, 0), else_=lines.c.credit)), 0),
            func.count().filter(~before),
        ).where(lines.c.account_id == account.id)
    ).one()

    # Solde progressif calculé sur toute la période (fonction de fenêtre), puis paginé :
    # chaque page affiche le solde exact, quelle que soit sa position.
    ordered = (
        select(
            JournalEntry.id.label("entry_id"),
            JournalEntry.entry_date,
            Journal.code.label("journal_code"),
            JournalEntry.number,
            JournalEntry.reference,
            func.coalesce(JournalLine.label, JournalEntry.label).label("label"),
            JournalLine.debit,
            JournalLine.credit,
            JournalLine.line_no,
            JournalLine.id.label("line_id"),
            (
                # NUMERIC : aucun débordement, quel que soit le montant.
                literal(int(opening), Numeric())
                + func.sum(JournalLine.debit - JournalLine.credit).over(
                    order_by=(
                        JournalEntry.entry_date,
                        Journal.code,
                        JournalEntry.number,
                        JournalLine.line_no,
                        JournalLine.id,
                    )
                )
            ).label("balance"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalLine.account_id == account.id,
            JournalEntry.fiscal_year_id == period.fiscal_year.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date >= period.date_from,
            JournalEntry.entry_date <= period.date_to,
            # Les à-nouveaux sont dans le solde d'ouverture, pas dans les mouvements.
            Journal.kind != JournalKind.A_NOUVEAUX,
        )
        .subquery()
    )
    rows = session.execute(
        select(ordered)
        # Même ordre que la fonction de fenêtre.
        .order_by(
            ordered.c.entry_date,
            ordered.c.journal_code,
            ordered.c.number,
            ordered.c.line_no,
            ordered.c.line_id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return AccountLedger(
        account=account,
        opening=int(opening),
        period_debit=int(period_debit),
        period_credit=int(period_credit),
        lines=[
            LedgerLine(
                r.entry_id,
                r.entry_date,
                r.journal_code,
                r.number,
                r.reference,
                r.label,
                int(r.debit),
                int(r.credit),
                int(r.balance),
            )
            for r in rows
        ],
        total_lines=int(count),
    )
