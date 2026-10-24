"""Verrouillage de période, clôture et réouverture d'exercice, à-nouveaux.

Clôture : l'exercice ne doit contenir aucun brouillon et l'exercice suivant doit
exister. Les soldes des comptes de bilan (classes 1 à 5) sont reportés en à-nouveaux,
le premier jour de l'exercice suivant, avec le résultat (classes 6, 7 et 8) au compte
131 « Résultat net : bénéfice » ou 139 « Résultat net : perte ». Les à-nouveaux
reproduisent donc exactement le bilan de clôture.

Réouverture : les à-nouveaux générés sont contre-passés (jamais supprimés), puis
l'exercice redevient modifiable. Elle est impossible si l'exercice suivant est clôturé.

À valider par un expert-comptable guinéen : comptes 131/139, classes de résultat,
report du résultat sans affectation (l'affectation suit la décision de l'assemblée),
détail des à-nouveaux (un solde par compte : les tiers doivent avoir leurs sous-comptes).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting import entries
from kora.accounting.entries import Actor, EntryData, LineData
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, NotFoundError
from kora.models.accounting import Account
from kora.models.common import utcnow
from kora.models.ledger import (
    MAX_LINES_PER_ENTRY,
    EntryOrigin,
    EntryStatus,
    Journal,
    JournalEntry,
    JournalKind,
    JournalLine,
)
from kora.models.organization import FiscalYear, FiscalYearStatus

BALANCE_SHEET_CLASSES = ("1", "2", "3", "4", "5")
INCOME_CLASSES = ("6", "7", "8")
PROFIT_ACCOUNT = "131"
LOSS_ACCOUNT = "139"


def _lock_year(session: Session, company_id: uuid.UUID, fiscal_year_id: uuid.UUID) -> FiscalYear:
    year = session.execute(
        select(FiscalYear)
        .where(FiscalYear.id == fiscal_year_id, FiscalYear.tenant_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if year is None:
        raise NotFoundError("Exercice introuvable.")
    return year


def _audit(
    session: Session, actor: Actor, action: str, year: FiscalYear, payload: dict[str, object]
) -> None:
    record_event(
        session,
        action=action,
        entity_type="fiscal_year",
        entity_id=year.id,
        payload={"debut": year.start_date.isoformat(), "fin": year.end_date.isoformat(), **payload},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )


def _drafts_until(session: Session, company_id: uuid.UUID, year: FiscalYear, until: date) -> int:
    return session.execute(
        select(func.count())
        .select_from(JournalEntry)
        .where(
            JournalEntry.tenant_id == company_id,
            JournalEntry.fiscal_year_id == year.id,
            JournalEntry.status == EntryStatus.DRAFT,
            JournalEntry.entry_date <= until,
        )
    ).scalar_one()


# --- Verrouillage de période


def lock_period(
    session: Session,
    actor: Actor,
    fiscal_year_id: uuid.UUID,
    until: date | None,
    *,
    can_unlock: bool,
) -> FiscalYear:
    """Fixe la date de verrouillage (None : aucun verrouillage). Reculer la date
    (déverrouiller) exige un droit supérieur, transmis par `can_unlock`."""
    year = _lock_year(session, actor.company_id, fiscal_year_id)
    if year.status != FiscalYearStatus.OPEN:
        raise BusinessRuleError("Exercice clôturé : rouvrez-le d'abord.")
    if until is not None and not (year.start_date <= until <= year.end_date):
        raise BusinessRuleError("La date de verrouillage doit être dans l'exercice.")
    previous = year.locked_until
    unlocking = previous is not None and (until is None or until < previous)
    if unlocking and not can_unlock:
        raise BusinessRuleError(
            "Seul un dirigeant ou un administrateur de cabinet peut déverrouiller."
        )
    if until is not None:
        drafts = _drafts_until(session, actor.company_id, year, until)
        if drafts:
            raise BusinessRuleError(
                f"{drafts} brouillon(s) daté(s) du {until:%d/%m/%Y} ou avant : validez-les ou "
                "supprimez-les avant de verrouiller."
            )
    year.locked_until = until
    _audit(
        session,
        actor,
        "fiscal_year.unlocked" if unlocking else "fiscal_year.locked",
        year,
        {
            "avant": previous.isoformat() if previous else None,
            "apres": until.isoformat() if until else None,
        },
    )
    session.commit()
    return year


# --- Clôture


@dataclass(frozen=True)
class ClosingPlan:
    year: FiscalYear
    next_year: FiscalYear | None
    drafts: int
    result: int  # bénéfice > 0, perte < 0
    lines: list[tuple[Account, int]]  # comptes de bilan et leur solde (positif = débiteur)
    issues: list[str]

    @property
    def ready(self) -> bool:
        return not self.issues


def _balances(
    session: Session, company_id: uuid.UUID, year: FiscalYear
) -> list[tuple[Account, int]]:
    rows = session.execute(
        select(Account, func.sum(JournalLine.debit - JournalLine.credit))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.fiscal_year_id == year.id,
            JournalEntry.status == EntryStatus.POSTED,
        )
        .group_by(Account.id)
        .order_by(Account.number)
    ).all()
    return [(account, int(net)) for account, net in rows if int(net) != 0]


def plan_closing(session: Session, company_id: uuid.UUID, fiscal_year_id: uuid.UUID) -> ClosingPlan:
    year = session.execute(
        select(FiscalYear).where(
            FiscalYear.id == fiscal_year_id, FiscalYear.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if year is None:
        raise NotFoundError("Exercice introuvable.")
    issues: list[str] = []
    if year.status != FiscalYearStatus.OPEN:
        issues.append("Cet exercice est déjà clôturé.")
    drafts = _drafts_until(session, company_id, year, year.end_date)
    if drafts:
        issues.append(f"{drafts} brouillon(s) à valider ou supprimer.")
    next_year = session.execute(
        select(FiscalYear).where(
            FiscalYear.tenant_id == company_id,
            FiscalYear.start_date == year.end_date + timedelta(days=1),
        )
    ).scalar_one_or_none()
    if next_year is None:
        issues.append(
            f"Créez d'abord l'exercice suivant (débutant le "
            f"{year.end_date + timedelta(days=1):%d/%m/%Y}) : il recevra les à-nouveaux."
        )
    elif next_year.status != FiscalYearStatus.OPEN:
        issues.append("L'exercice suivant est clôturé.")
    balances = _balances(session, company_id, year)
    result = -sum(net for account, net in balances if account.number.startswith(INCOME_CLASSES))
    sheet = [(a, net) for a, net in balances if a.number.startswith(BALANCE_SHEET_CLASSES)]
    if len(sheet) + 1 > MAX_LINES_PER_ENTRY:
        issues.append(
            f"{len(sheet)} comptes de bilan soldés : au-delà de {MAX_LINES_PER_ENTRY - 1}, "
            "les à-nouveaux ne tiennent pas en une écriture. Contactez le support."
        )
    return ClosingPlan(year, next_year, drafts, result, sheet, issues)


def _account(session: Session, company_id: uuid.UUID, number: str) -> Account:
    account = session.execute(
        select(Account).where(Account.tenant_id == company_id, Account.number == number)
    ).scalar_one_or_none()
    if account is None:
        raise BusinessRuleError(
            f"Compte {number} absent du plan comptable : il reçoit le résultat."
        )
    return account


def _closing_reference(year: FiscalYear) -> str:
    return f"CLOTURE {year.start_date:%Y-%m-%d}"


def close(
    session: Session, actor: Actor, fiscal_year_id: uuid.UUID
) -> tuple[FiscalYear, uuid.UUID | None]:
    year = _lock_year(session, actor.company_id, fiscal_year_id)
    plan = plan_closing(session, actor.company_id, fiscal_year_id)
    if not plan.ready:
        raise BusinessRuleError("Clôture impossible.", errors=plan.issues)
    assert plan.next_year is not None  # noqa: S101 (garanti par plan.ready)
    journal = (
        session.execute(
            select(Journal)
            .where(
                Journal.tenant_id == actor.company_id,
                Journal.kind == JournalKind.A_NOUVEAUX,
                Journal.is_active.is_(True),
            )
            .order_by(Journal.code)
        )
        .scalars()
        .first()
    )
    if journal is None:
        raise BusinessRuleError("Aucun journal d'à-nouveaux actif : créez-en un (type À-nouveaux).")

    lines = [
        LineData(account_id=account.id, debit=max(net, 0), credit=max(-net, 0))
        for account, net in plan.lines
    ]
    if plan.result > 0:
        lines.append(
            LineData(
                account_id=_account(session, actor.company_id, PROFIT_ACCOUNT).id,
                credit=plan.result,
            )
        )
    elif plan.result < 0:
        lines.append(
            LineData(
                account_id=_account(session, actor.company_id, LOSS_ACCOUNT).id, debit=-plan.result
            )
        )

    entry_id: uuid.UUID | None = None
    if lines:
        entry = JournalEntry(
            tenant_id=actor.company_id,
            created_by_user_id=actor.user_id,
            status=EntryStatus.DRAFT,
            origin=EntryOrigin.CLOSING,
        )
        data = EntryData(
            journal_id=journal.id,
            entry_date=plan.next_year.start_date,
            label=(
                f"À-nouveaux de l'exercice du {year.start_date:%d/%m/%Y} "
                f"au {year.end_date:%d/%m/%Y}"
            ),
            reference=_closing_reference(year),
            lines=lines,
        )
        entries.apply_generated(session, actor, entry, data)
        entries.post_generated(session, actor, entry)
        entry_id = entry.id

    year.status = FiscalYearStatus.CLOSED
    year.closed_at = utcnow()
    year.closed_by_user_id = actor.user_id
    _audit(
        session,
        actor,
        "fiscal_year.closed",
        year,
        {
            "resultat": plan.result,
            "a_nouveaux": str(entry_id) if entry_id else None,
            "comptes_reportes": len(plan.lines),
        },
    )
    session.commit()
    return year, entry_id


def reopen(session: Session, actor: Actor, fiscal_year_id: uuid.UUID) -> FiscalYear:
    year = _lock_year(session, actor.company_id, fiscal_year_id)
    if year.status != FiscalYearStatus.CLOSED:
        raise BusinessRuleError("Cet exercice n'est pas clôturé.")
    next_year = session.execute(
        select(FiscalYear)
        .where(
            FiscalYear.tenant_id == actor.company_id,
            FiscalYear.start_date == year.end_date + timedelta(days=1),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if next_year is not None and next_year.status != FiscalYearStatus.OPEN:
        raise BusinessRuleError("L'exercice suivant est clôturé : rouvrez-le d'abord.")
    # À-nouveaux générés par cette clôture et pas encore contre-passés.
    reversed_ids = select(JournalEntry.reversal_of_id).where(
        JournalEntry.tenant_id == actor.company_id, JournalEntry.reversal_of_id.is_not(None)
    )
    generated = (
        session.execute(
            select(JournalEntry.id).where(
                JournalEntry.tenant_id == actor.company_id,
                JournalEntry.origin == EntryOrigin.CLOSING,
                JournalEntry.reference == _closing_reference(year),
                JournalEntry.reversal_of_id.is_(None),
                JournalEntry.status == EntryStatus.POSTED,
                JournalEntry.id.not_in(reversed_ids),
            )
        )
        .scalars()
        .all()
    )
    # Réouvert avant la contre-passation : les écritures de cet exercice redeviennent
    # possibles, et la contre-passation se fait dans l'exercice suivant (ouvert).
    year.status = FiscalYearStatus.OPEN
    year.closed_at = None
    year.closed_by_user_id = None
    session.flush()
    for entry_id in generated:
        assert next_year is not None  # noqa: S101 (les à-nouveaux sont dans l'exercice suivant)
        entries.reverse_entry(
            session, actor, entry_id, reversal_date=next_year.start_date, commit=False
        )
    _audit(
        session, actor, "fiscal_year.reopened", year, {"a_nouveaux_contre_passes": len(generated)}
    )
    session.commit()
    return year
