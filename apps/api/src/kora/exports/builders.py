"""Construction des documents exportés (balance, grand livre, écritures, états)."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting import cashflows, reports, statements
from kora.accounting.reports import AccountFilter, Period
from kora.exports.document import Column, Document, Section, format_date
from kora.models.accounting import Account
from kora.models.identity import Company
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalLine
from kora.sales import payments

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


def cash_flows(session: Session, company: Company, period: Period) -> Document:
    """Tableau des flux de trésorerie (méthode directe, KF-15) : exercice N, N-1 en
    comparaison s'il existe, comme la page web et la route JSON."""
    current = cashflows.compute(session, company.id, period.fiscal_year, period.date_to)
    before = cashflows.previous_year(session, company.id, period.fiscal_year)
    previous = cashflows.compute(session, company.id, before) if before else None
    document = _document(
        company, "Tableau des flux de trésorerie — SYSCOHADA révisé (méthode directe)", period
    )
    document.notes.append(EXPERT_NOTICE)
    document.notes.append(f"Référentiel : {cashflows.REFERENCE}.")
    if not current.coherent:
        detail = (
            "ATTENTION : divergence de trésorerie — ouverture + variation ne rapproche pas le "
            f"solde réel de la classe 5 ({current.treasury_at_end} ≠ {current.closing})"
        )
        if current.unmapped:
            detail += f" ; comptes sans affectation TFT : {', '.join(current.unmapped)}"
        document.notes.append(detail + " — anomalie à signaler.")
    section = Section(
        "Tableau des flux de trésorerie",
        [
            Column("Réf.", width=7),
            Column("Poste", width=54),
            Column("N", "amount", 14),
            Column("N-1", "amount", 14),
        ],
    )
    for line in cashflows.template():
        prev = previous.amount(line.code) if previous else None
        if line.kind == "section":
            section.add(line.code, line.label, None, None, style="heading")
        else:
            section.add(
                line.code,
                line.label,
                current.amount(line.code),
                prev,
                style="total" if line.kind == "total" else "normal",
            )
    document.sections.append(section)
    return document


AGING_BUCKET_LABELS = {
    "not_due": "À échoir (échéance non passée)",
    "d1_30": "Retard 1 à 30 jours",
    "d31_60": "Retard 31 à 60 jours",
    "d61_90": "Retard 61 à 90 jours",
    "d90_plus": "Retard plus de 90 jours",
}


def receivables_aging(session: Session, company: Company, as_of: date) -> Document:
    """Balance âgée clients détaillée au {as_of} (lot B-4) : une section par
    bucket, une ligne par facture émise non soldée — exactement la même
    répartition que la route JSON 4C (mêmes soldes, mêmes buckets)."""
    rows = payments.receivables_aging_rows(session, company.id, as_of)
    document = Document(
        title="Balance âgée clients",
        company_name=company.legal_name,
        identifiers=(
            " — ".join(
                i
                for i in (
                    f"RCCM : {company.rccm}" if company.rccm else None,
                    f"NIF : {company.nif}" if company.nif else None,
                )
                if i
            )
            or "RCCM et NIF non renseignés"
        ),
        period=f"Situation au {format_date(as_of)}",
        currency=company.currency,
        generated_at=datetime.now(UTC),
        notes=[
            "Factures émises non soldées : solde = TTC - règlements lettrés- avoirs partiels émis.",
            "À échoir : échéance non passée au jour de la situation.",
        ],
        landscape=True,
    )
    grand_total = 0
    for bucket in ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus"):
        section = Section(
            AGING_BUCKET_LABELS[bucket],
            [
                Column("Facture", width=10),
                Column("Tier", width=34),
                Column("Émission", "date", 12),
                Column("Échéance", "date", 12),
                Column("Retard (j)", "number", 10),
                Column("Solde TTC", "amount", 16),
            ],
        )
        sous_total = 0
        for row in sorted(
            (r for r in rows if r.bucket == bucket), key=lambda r: (-r.days_late, r.number)
        ):
            sous_total += row.outstanding_ttc
            section.add(
                f"FAC-{row.number:05d}",
                row.partner_name,
                row.issued_on,
                row.due_on,
                row.days_late,
                row.outstanding_ttc,
            )
        section.add(None, "Sous-total", None, None, None, sous_total, style="subtotal")
        grand_total += sous_total
        document.sections.append(section)
    total = Section(
        None,
        [
            Column("Total", width=10),
            Column("Factures", width=34),
            Column("Émission", "date", 12),
            Column("Échéance", "date", 12),
            Column("Retard (j)", "number", 10),
            Column("Solde TTC", "amount", 16),
        ],
    )
    total.add(
        "Encours total", f"{len(rows)} facture(s)", None, None, None, grand_total, style="total"
    )
    document.sections.append(total)
    return document
