"""Tableau de bord d'un dossier : indicateurs calculés sur les écritures **validées**.

Une seule requête agrège les lignes validées de l'exercice qui couvre la date demandée,
par compte et par mois ; les regroupements sont faits ensuite en entiers (unités
mineures), sans flottant. Les brouillons ne sont que comptés.

Regroupements (à valider par un expert-comptable guinéen) :
- trésorerie disponible = comptes 52 (banques), 53 (établissements financiers),
  55 (monnaie électronique / Mobile Money) et 57 (caisse), soldes débiteurs ou non ;
- chiffre d'affaires = comptes 70 (ventes), crédit - débit ;
- charges = classe 6, débit - crédit ; produits = classe 7, crédit - débit ;
- résultat provisoire = crédit - débit des classes 6, 7 et 8 (avant écritures
  d'inventaire : amortissements, provisions, stocks) ;
- clients à encaisser = solde débiteur net des comptes 41 ; fournisseurs à payer =
  solde créditeur net des comptes 40.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from kora.models.accounting import Account
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalKind, JournalLine
from kora.models.organization import FiscalYear

TREASURY_PREFIXES = ("52", "53", "55", "57")
RECENT_MONTHS = 12


@dataclass(frozen=True)
class AccountBalance:
    account_id: uuid.UUID
    number: str
    label: str
    balance: int  # positif = débiteur


@dataclass
class Figures:
    revenue: int = 0
    income: int = 0
    expenses: int = 0
    result: int = 0


@dataclass(frozen=True)
class MonthFigures:
    month: date  # premier jour du mois
    revenue: int
    expenses: int


@dataclass
class Dashboard:
    as_of: date
    fiscal_year: FiscalYear | None
    treasury: list[AccountBalance] = field(default_factory=list)
    receivables: int = 0
    payables: int = 0
    month: Figures = field(default_factory=Figures)
    year_to_date: Figures = field(default_factory=Figures)
    monthly: list[MonthFigures] = field(default_factory=list)
    drafts: int = 0

    @property
    def treasury_total(self) -> int:
        return sum(a.balance for a in self.treasury)


def _fiscal_year(session: Session, company_id: uuid.UUID, as_of: date) -> FiscalYear | None:
    """Exercice qui couvre la date ; à défaut, le plus récent déjà commencé."""
    covering = session.execute(
        select(FiscalYear).where(
            FiscalYear.tenant_id == company_id,
            FiscalYear.start_date <= as_of,
            FiscalYear.end_date >= as_of,
        )
    ).scalar_one_or_none()
    if covering is not None:
        return covering
    return session.execute(
        select(FiscalYear)
        .where(FiscalYear.tenant_id == company_id, FiscalYear.start_date <= as_of)
        .order_by(FiscalYear.start_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _add(figures: Figures, number: str, debit: int, credit: int) -> None:
    net_credit = credit - debit
    if number.startswith("70"):
        figures.revenue += net_credit
    if number.startswith("7"):
        figures.income += net_credit
    if number.startswith("6"):
        figures.expenses += debit - credit
    if number[0] in "678":
        figures.result += net_credit


def _months(start: date, end: date) -> list[date]:
    months: list[date] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months[-RECENT_MONTHS:]


def compute(session: Session, company_id: uuid.UUID, as_of: date) -> Dashboard:
    fiscal_year = _fiscal_year(session, company_id, as_of)
    drafts = session.execute(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.tenant_id == company_id, JournalEntry.status == EntryStatus.DRAFT)
    ).scalar_one()
    dashboard = Dashboard(as_of=as_of, fiscal_year=fiscal_year, drafts=drafts)
    if fiscal_year is None:
        return dashboard
    until = min(as_of, fiscal_year.end_date)

    month = cast(func.date_trunc("month", JournalEntry.entry_date), Date).label("month")
    opening = (Journal.kind == JournalKind.A_NOUVEAUX).label("opening")
    rows = session.execute(
        select(
            Account.id,
            Account.number,
            Account.label,
            month,
            opening,
            func.sum(JournalLine.debit),
            func.sum(JournalLine.credit),
        )
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .where(
            Account.tenant_id == company_id,
            JournalLine.tenant_id == company_id,
            JournalEntry.tenant_id == company_id,
            JournalEntry.fiscal_year_id == fiscal_year.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date <= until,
        )
        .group_by(Account.id, Account.number, Account.label, month, opening)
    ).all()

    balances: dict[uuid.UUID, AccountBalance] = {}
    revenue_by_month: dict[date, int] = defaultdict(int)
    expenses_by_month: dict[date, int] = defaultdict(int)
    current_month = date(until.year, until.month, 1)
    for account_id, number, label, row_month, is_opening, debit_sum, credit_sum in rows:
        debit, credit = int(debit_sum), int(credit_sum)
        previous = balances.get(account_id)
        balances[account_id] = AccountBalance(
            account_id, number, label, (previous.balance if previous else 0) + debit - credit
        )
        if is_opening:
            continue  # les à-nouveaux ne sont pas une activité de la période
        _add(dashboard.year_to_date, number, debit, credit)
        if row_month == current_month:
            _add(dashboard.month, number, debit, credit)
        if number.startswith("70"):
            revenue_by_month[row_month] += credit - debit
        if number.startswith("6"):
            expenses_by_month[row_month] += debit - credit

    for balance in balances.values():
        if balance.number.startswith("41"):
            dashboard.receivables += balance.balance
        elif balance.number.startswith("40"):
            dashboard.payables -= balance.balance
    dashboard.treasury = sorted(
        (b for b in balances.values() if b.number.startswith(TREASURY_PREFIXES)),
        key=lambda b: b.number,
    )
    dashboard.monthly = [
        MonthFigures(m, revenue_by_month.get(m, 0), expenses_by_month.get(m, 0))
        for m in _months(fiscal_year.start_date, until)
    ]
    return dashboard
