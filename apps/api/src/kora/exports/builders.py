"""Construction des documents exportés (balance, grand livre, écritures, états)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting import reports, statements
from kora.accounting.reports import AccountFilter, Period
from kora.exports.document import Column, Document, Section, format_date
from kora.models.accounting import Account
from kora.models.identity import Company
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalLine

VALIDATED_ONLY = "Écritures validées uniquement (les brouillons sont exclus)."
EXPERT_NOTICE = (
    "Présentation et affectation des comptes à valider par un expert-comptable guinéen "
    "avant tout usage officiel."
)


def _document(company: Company, title: str, period: Period, *, landscape: bool = False) -> Document:
    ids = [
        f"RCCM : {company.rccm}" if company.rccm else None,
        f"NIF : {company.nif}" if company.nif else None,
    ]
    return Document(
        title=title,
        company_name=company.legal_name,
        identifiers=" — ".join(i for i in ids if i) or "RCCM et NIF non renseignés",
        period=f"Période du {format_date(period.date_from)} au {format_date(period.date_to)}",
        currency=company.currency,
        generated_at=datetime.now(UTC),
        notes=[VALIDATED_ONLY],
        landscape=landscape,
    )


def trial_balance(session: Session, company: Company, period: Period) -> Document:
    document = _document(company, "Balance générale", period, landscape=True)
    section = Section(
        None,
        [
            Column("Compte", width=8),
            Column("Libellé", width=34),
            Column("Ouverture débit", "amount", 14),
            Column("Ouverture crédit", "amount", 14),
            Column("Mouvements débit", "amount", 14),
            Column("Mouvements crédit", "amount", 14),
            Column("Solde débiteur", "amount", 14),
            Column("Solde créditeur", "amount", 14),
        ],
    )
    totals = [0] * 6
    for row in reports.trial_balance(session, company.id, period, AccountFilter()):
        values = [
            max(row.opening, 0),
            max(-row.opening, 0),
            row.period_debit,
            row.period_credit,
            max(row.closing, 0),
            max(-row.closing, 0),
        ]
        totals = [a + b for a, b in zip(totals, values, strict=True)]
        section.add(row.number, row.label, *values)
    section.add(None, "Total général", *totals, style="total")
    document.sections.append(section)
    if not (totals[0] == totals[1] and totals[2] == totals[3] and totals[4] == totals[5]):
        document.notes.append("ATTENTION : balance déséquilibrée — anomalie à signaler au support.")
    return document


def ledger(
    session: Session, company: Company, period: Period, account_id: uuid.UUID | None
) -> Document:
    document = _document(company, "Grand livre", period, landscape=True)
    accounts = reports.full_ledger(session, company.id, period)
    if account_id is not None:
        accounts = [a for a in accounts if a.account_id == account_id]
    columns = [
        Column("Date", "date", 10),
        Column("Journal", width=7),
        Column("N°", "number", 6),
        Column("Pièce", width=12),
        Column("Libellé", width=40),
        Column("Débit", "amount", 14),
        Column("Crédit", "amount", 14),
        Column("Solde", "amount", 15),
    ]
    section = Section(None, columns)
    for account in accounts:
        section.add(
            None,
            None,
            None,
            None,
            f"{account.number} — {account.label}",
            None,
            None,
            None,
            style="heading",
        )
        section.add(
            None,
            None,
            None,
            None,
            "Solde d'ouverture",
            None,
            None,
            account.opening,
            style="subtotal",
        )
        for line in account.lines:
            section.add(
                line.entry_date,
                line.journal_code,
                line.number,
                line.reference,
                line.label,
                line.debit or None,
                line.credit or None,
                line.balance,
            )
        section.add(
            None,
            None,
            None,
            None,
            f"Total {account.number} et solde de clôture",
            account.period_debit,
            account.period_credit,
            account.closing,
            style="subtotal",
        )
    document.sections.append(section)
    document.notes.append("Solde : positif = débiteur, négatif = créditeur.")
    return document


def entries(session: Session, company: Company, period: Period) -> Document:
    document = _document(company, "Journal des écritures", period, landscape=True)
    rows = session.execute(
        select(JournalEntry, Journal.code, JournalLine, Account.number, Account.label)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(
            JournalEntry.tenant_id == company.id,
            JournalEntry.fiscal_year_id == period.fiscal_year.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date >= period.date_from,
            JournalEntry.entry_date <= period.date_to,
        )
        .order_by(Journal.code, JournalEntry.number, JournalLine.line_no)
    ).all()
    section = Section(
        None,
        [
            Column("Journal", width=7),
            Column("N°", "number", 6),
            Column("Date", "date", 10),
            Column("Pièce", width=12),
            Column("Compte", width=8),
            Column("Libellé", width=40),
            Column("Débit", "amount", 14),
            Column("Crédit", "amount", 14),
        ],
    )
    total_debit = total_credit = 0
    for entry, code, line, number, account_label in rows:
        section.add(
            code,
            entry.number,
            entry.entry_date,
            entry.reference,
            number,
            line.label or f"{entry.label} ({account_label})",
            line.debit or None,
            line.credit or None,
        )
        total_debit += line.debit
        total_credit += line.credit
    section.add(None, None, None, None, None, "Total", total_debit, total_credit, style="total")
    document.sections.append(section)
    return document


def financial_statements(session: Session, company: Company, period: Period) -> Document:
    current = statements.compute(session, company.id, period.fiscal_year, period.date_to)
    before = statements.previous_year(session, company.id, period.fiscal_year)
    previous = statements.compute(session, company.id, before) if before else None
    document = _document(company, "États financiers — système normal SYSCOHADA révisé", period)
    document.notes.append(EXPERT_NOTICE)
    document.notes.append(f"Référentiel : {statements.REFERENCE}.")
    if not current.balanced:
        document.notes.append(
            "ATTENTION : bilan déséquilibré ou comptes non affectés — anomalie à signaler."
        )
    lines = statements.template()

    assets = Section(
        "Bilan — Actif",
        [
            Column("Réf.", width=7),
            Column("Actif", width=40),
            Column("Brut", "amount", 14),
            Column("Amort. et dépréc.", "amount", 14),
            Column("Net N", "amount", 14),
            Column("Net N-1", "amount", 14),
        ],
    )
    liabilities = Section(
        "Bilan — Passif",
        [
            Column("Réf.", width=7),
            Column("Passif", width=54),
            Column("N", "amount", 14),
            Column("N-1", "amount", 14),
        ],
    )
    income = Section(
        "Compte de résultat",
        [
            Column("Réf.", width=7),
            Column("Poste", width=54),
            Column("N", "amount", 14),
            Column("N-1", "amount", 14),
        ],
    )
    for line in lines:
        amounts = current.values[line.code]
        prev = previous.amount(line.code) if previous else None
        is_total = line.kind == "total"
        if line.statement == "ACTIF":
            assets.add(
                line.code,
                line.label,
                amounts.gross,
                amounts.depreciation,
                amounts.net,
                prev,
                style="total" if is_total else "normal",
            )
        else:
            target = liabilities if line.statement == "PASSIF" else income
            target.add(
                line.code, line.label, amounts.net, prev, style="total" if is_total else "normal"
            )
    document.sections += [assets, liabilities, income]
    return document
