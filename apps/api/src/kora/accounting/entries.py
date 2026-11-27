"""Écritures comptables en partie double.

Cycle de vie :
- **brouillon** : librement modifiable et supprimable, sans numéro, éventuellement
  déséquilibré (saisie en plusieurs fois, saisie hors connexion) ;
- **validée** : contrôlée (équilibre, comptes, exercice), numérotée sans trou dans son
  journal et son exercice, puis immuable. Une erreur se corrige par contre-passation.

La base impose les mêmes invariants (déclencheurs de la migration 0005) : ce module
donne des messages clairs, la base garantit qu'aucun chemin ne les contourne.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.attachments import service as attachments
from kora.audit.service import record_event
from kora.auth.service import RequestContext
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account
from kora.models.common import utcnow
from kora.models.ledger import (
    MAX_LINE_AMOUNT,
    MAX_LINES_PER_ENTRY,
    EntryOrigin,
    EntryStatus,
    Journal,
    JournalEntry,
    JournalKind,
    JournalLine,
    JournalSequence,
)
from kora.models.organization import FiscalYear, FiscalYearStatus


@dataclass(frozen=True)
class LineData:
    account_id: uuid.UUID
    debit: int = 0
    credit: int = 0
    label: str | None = None


@dataclass(frozen=True)
class EntryData:
    journal_id: uuid.UUID
    entry_date: date
    label: str
    lines: Sequence[LineData]
    reference: str | None = None


@dataclass(frozen=True)
class Actor:
    company_id: uuid.UUID
    user_id: uuid.UUID
    ctx: RequestContext = field(default_factory=RequestContext)


@dataclass(frozen=True)
class EntryView:
    entry: JournalEntry
    journal: Journal
    lines: list[tuple[JournalLine, Account]]

    @property
    def total(self) -> int:
        return sum(line.debit for line, _ in self.lines)


# --- Contrôles


def _fiscal_year_for(
    session: Session, company_id: uuid.UUID, day: date, *, lock: bool = False
) -> FiscalYear:
    """Exercice couvrant `day`. `lock` (validation) : verrou de ligne `FOR UPDATE`, même
    protocole que le déclencheur (migration 0010) et que `closing._lock_year` — la
    validation attend la fin d'une clôture ou d'un verrouillage concurrent, et l'ordre
    « exercice puis numérotation » est uniforme dans toutes les transactions (pas
    d'interblocage avec `_next_number`)."""
    query = select(FiscalYear).where(
        FiscalYear.tenant_id == company_id,
        FiscalYear.start_date <= day,
        FiscalYear.end_date >= day,
    )
    if lock:
        query = query.with_for_update()
    fiscal_year = session.execute(query).scalar_one_or_none()
    if fiscal_year is None:
        raise BusinessRuleError(
            f"Aucun exercice ne couvre le {day:%d/%m/%Y}. Créez d'abord l'exercice."
        )
    if fiscal_year.status != FiscalYearStatus.OPEN:
        raise BusinessRuleError(f"L'exercice qui couvre le {day:%d/%m/%Y} est clôturé.")
    if fiscal_year.locked_until is not None and day <= fiscal_year.locked_until:
        raise BusinessRuleError(
            f"Période verrouillée jusqu'au {fiscal_year.locked_until:%d/%m/%Y} : "
            "aucune écriture ne peut y être saisie ou validée."
        )
    return fiscal_year


def check_entry_date(session: Session, company_id: uuid.UUID, day: date) -> None:
    """Refuse une date hors exercice ouvert ou dans une période verrouillée."""
    _fiscal_year_for(session, company_id, day)


def _check_lines_shape(lines: Sequence[LineData]) -> None:
    if not lines:
        raise BusinessRuleError("Une écriture comporte au moins une ligne.")
    if len(lines) > MAX_LINES_PER_ENTRY:
        raise BusinessRuleError(f"Une écriture comporte au plus {MAX_LINES_PER_ENTRY} lignes.")
    errors = []
    for number, line in enumerate(lines, start=1):
        if line.debit < 0 or line.credit < 0:
            errors.append(f"Ligne {number} : montant négatif.")
        elif (line.debit == 0) == (line.credit == 0):
            errors.append(
                f"Ligne {number} : saisir un montant au débit ou au crédit, pas les deux."
            )
        elif max(line.debit, line.credit) > MAX_LINE_AMOUNT:
            errors.append(f"Ligne {number} : montant trop élevé.")
    if errors:
        raise BusinessRuleError("Lignes d'écriture invalides.", errors=errors)


def _accounts(
    session: Session, company_id: uuid.UUID, account_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Account]:
    found = {
        a.id: a
        for a in session.execute(
            select(Account).where(Account.tenant_id == company_id, Account.id.in_(account_ids))
        ).scalars()
    }
    missing = account_ids - found.keys()
    if missing:
        # Compte d'un autre dossier ou inexistant : même réponse.
        raise BusinessRuleError("Compte introuvable dans le plan comptable du dossier.")
    return found


def _accounts_with_subaccounts(
    session: Session, company_id: uuid.UUID, accounts: Sequence[Account]
) -> list[str]:
    """Comptes de regroupement : ils ont des sous-comptes, on impute sur ceux-ci."""
    numbers = sorted({a.number for a in accounts})
    child = Account.__table__.alias("child")
    parent = Account.__table__.alias("parent")
    rows = session.execute(
        select(parent.c.number)
        .where(parent.c.tenant_id == company_id, parent.c.number.in_(numbers))
        .where(
            select(child.c.id)
            .where(
                child.c.tenant_id == company_id,
                child.c.number.like(parent.c.number + "_%"),
            )
            .exists()
        )
    ).scalars()
    return sorted(rows)


def _get_journal(session: Session, company_id: uuid.UUID, journal_id: uuid.UUID) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.id == journal_id, Journal.tenant_id == company_id)
    ).scalar_one_or_none()
    if journal is None:
        raise BusinessRuleError("Journal introuvable.")
    if not journal.is_active:
        raise BusinessRuleError(f"Le journal {journal.code} est désactivé.")
    return journal


def _lock_entry(session: Session, actor: Actor, entry_id: uuid.UUID) -> JournalEntry:
    entry = session.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.tenant_id == actor.company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if entry is None:
        raise NotFoundError("Écriture introuvable.")
    return entry


def _require_draft(entry: JournalEntry) -> None:
    if entry.status != EntryStatus.DRAFT:
        raise ConflictError(
            "Cette écriture est validée : elle ne peut plus être modifiée. "
            "Corrigez-la par une contre-passation."
        )


def _audit(
    session: Session, actor: Actor, action: str, entry_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    record_event(
        session,
        action=action,
        entity_type="journal_entry",
        entity_id=entry_id,
        payload=payload,
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )


def _write_lines(
    session: Session, actor: Actor, entry: JournalEntry, lines: Sequence[LineData]
) -> None:
    session.execute(delete(JournalLine).where(JournalLine.entry_id == entry.id))
    session.add_all(
        JournalLine(
            tenant_id=actor.company_id,
            entry_id=entry.id,
            line_no=number,
            account_id=line.account_id,
            label=(line.label or "").strip() or None,
            debit=line.debit,
            credit=line.credit,
        )
        for number, line in enumerate(lines, start=1)
    )


def _apply(session: Session, actor: Actor, entry: JournalEntry, data: EntryData) -> None:
    _check_lines_shape(data.lines)
    if not data.label.strip():
        raise BusinessRuleError("Le libellé de l'écriture est obligatoire.")
    journal = _get_journal(session, actor.company_id, data.journal_id)
    fiscal_year = _fiscal_year_for(session, actor.company_id, data.entry_date)
    _accounts(session, actor.company_id, {line.account_id for line in data.lines})
    entry.journal_id = journal.id
    entry.fiscal_year_id = fiscal_year.id
    entry.entry_date = data.entry_date
    entry.label = data.label.strip()
    entry.reference = (data.reference or "").strip() or None


# --- Brouillons


def create_draft(
    session: Session,
    actor: Actor,
    data: EntryData,
    *,
    entry_id: uuid.UUID | None = None,
    commit: bool = True,
) -> tuple[JournalEntry, bool]:
    """Crée un brouillon. `entry_id` fourni par le client rend la création idempotente
    (renvoi d'un brouillon saisi hors connexion) : renvoie (écriture, créée ?).
    `commit=False` : l'appelant (confirmation d'un import) écrit ses propres lignes
    de traçabilité et sa trace d'audit dans la même transaction, avant un commit unique."""
    if entry_id is not None:
        existing = session.execute(
            select(JournalEntry).where(
                JournalEntry.id == entry_id, JournalEntry.tenant_id == actor.company_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    entry = JournalEntry(
        id=entry_id or uuid.uuid4(),
        tenant_id=actor.company_id,
        created_by_user_id=actor.user_id,
        status=EntryStatus.DRAFT,
    )
    _apply(session, actor, entry, data)
    session.add(entry)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Cet identifiant d'écriture est déjà utilisé.") from exc
    _write_lines(session, actor, entry, data.lines)
    if commit:
        session.commit()
    return entry, True


def update_draft(
    session: Session, actor: Actor, entry_id: uuid.UUID, data: EntryData
) -> JournalEntry:
    entry = _lock_entry(session, actor, entry_id)
    _require_draft(entry)
    _apply(session, actor, entry, data)
    _write_lines(session, actor, entry, data.lines)
    session.commit()
    return entry


def delete_draft(session: Session, actor: Actor, entry_id: uuid.UUID) -> None:
    entry = _lock_entry(session, actor, entry_id)
    _require_draft(entry)
    keys = attachments.detach_all(session, actor.company_id, entry.id)
    session.delete(entry)
    session.commit()
    attachments.purge(keys)


# --- Validation


def _next_number(
    session: Session, actor: Actor, journal_id: uuid.UUID, fiscal_year_id: uuid.UUID
) -> int:
    session.execute(
        pg_insert(JournalSequence)
        .values(tenant_id=actor.company_id, journal_id=journal_id, fiscal_year_id=fiscal_year_id)
        .on_conflict_do_nothing()
    )
    sequence = session.execute(
        select(JournalSequence)
        .where(
            JournalSequence.tenant_id == actor.company_id,
            JournalSequence.journal_id == journal_id,
            JournalSequence.fiscal_year_id == fiscal_year_id,
        )
        .with_for_update()
    ).scalar_one()
    sequence.last_number += 1
    return sequence.last_number


def _post(session: Session, actor: Actor, entry: JournalEntry, *, system: bool = False) -> None:
    """Contrôle et valide. `system` : écriture générée par la clôture (à-nouveaux), qui
    reporte des soldes existants : comptes désactivés ou devenus de regroupement admis."""
    lines = list(
        session.execute(
            select(JournalLine)
            .where(JournalLine.entry_id == entry.id)
            .order_by(JournalLine.line_no)
        ).scalars()
    )
    errors = []
    if len(lines) < 2:
        errors.append("Une écriture validée comporte au moins deux lignes.")
    debit = sum(line.debit for line in lines)
    credit = sum(line.credit for line in lines)
    if debit != credit:
        errors.append(
            f"Écriture déséquilibrée : débit {debit}, crédit {credit} (écart {debit - credit})."
        )
    if errors:
        raise BusinessRuleError("Validation impossible.", errors=errors)

    journal = _get_journal(session, actor.company_id, entry.journal_id)
    fiscal_year = _fiscal_year_for(session, actor.company_id, entry.entry_date, lock=True)
    if fiscal_year.id != entry.fiscal_year_id:
        raise BusinessRuleError("La date de l'écriture n'appartient plus à son exercice.")
    if journal.kind == JournalKind.A_NOUVEAUX and entry.entry_date != fiscal_year.start_date:
        raise BusinessRuleError(
            "Les à-nouveaux sont datés du premier jour de l'exercice "
            f"({fiscal_year.start_date:%d/%m/%Y})."
        )
    accounts = _accounts(session, actor.company_id, {line.account_id for line in lines})
    inactive = sorted(a.number for a in accounts.values() if not a.is_active)
    if inactive and not system:
        raise BusinessRuleError("Comptes désactivés : " + ", ".join(inactive) + ".")
    grouping = (
        []
        if system
        else _accounts_with_subaccounts(session, actor.company_id, list(accounts.values()))
    )
    if grouping:
        raise BusinessRuleError(
            "Ces comptes ont des sous-comptes : imputez l'écriture sur un sous-compte.",
            errors=[f"Compte {n}" for n in grouping],
        )

    entry.number = _next_number(session, actor, journal.id, fiscal_year.id)
    entry.status = EntryStatus.POSTED
    entry.posted_at = utcnow()
    entry.posted_by_user_id = actor.user_id
    session.flush()
    _audit(
        session,
        actor,
        "entry.posted",
        entry.id,
        {
            "journal": journal.code,
            "numero": entry.number,
            "date": entry.entry_date.isoformat(),
            "libelle": entry.label,
            "total": debit,
            "lignes": [
                {
                    "compte": accounts[line.account_id].number,
                    "debit": line.debit,
                    "credit": line.credit,
                }
                for line in lines
            ],
        },
    )


def apply_generated(session: Session, actor: Actor, entry: JournalEntry, data: EntryData) -> None:
    """Écriture générée par le système (à-nouveaux) : mêmes contrôles de structure, sans
    l'exigence de comptes actifs (on reporte des soldes existants)."""
    _check_lines_shape(data.lines)
    entry.journal_id = _get_journal(session, actor.company_id, data.journal_id).id
    entry.fiscal_year_id = _fiscal_year_for(session, actor.company_id, data.entry_date).id
    entry.entry_date = data.entry_date
    entry.label = data.label
    entry.reference = data.reference
    session.add(entry)
    session.flush()
    _write_lines(session, actor, entry, data.lines)
    session.flush()


def post_generated(session: Session, actor: Actor, entry: JournalEntry) -> None:
    _post(session, actor, entry, system=True)


def post_pending(session: Session, actor: Actor, entry: JournalEntry) -> None:
    """Valide une écriture déjà préparée en session, sans commiter : le module appelant
    (trésorerie) écrit ensuite sa trace opérationnelle et l'audit dans la même
    transaction, avant le commit unique. Mêmes contrôles que `post_entry` (comptes
    actifs, équilibre, exercice ouvert, numérotation)."""
    _post(session, actor, entry, system=False)


def post_entry(session: Session, actor: Actor, entry_id: uuid.UUID) -> JournalEntry:
    entry = _lock_entry(session, actor, entry_id)
    _require_draft(entry)
    _post(session, actor, entry)
    session.commit()
    return entry


def reverse_entry(
    session: Session,
    actor: Actor,
    entry_id: uuid.UUID,
    *,
    reversal_date: date,
    commit: bool = True,
) -> JournalEntry:
    """Contre-passation : écriture validée inverse (débits ↔ crédits), liée à l'originale."""
    original = _lock_entry(session, actor, entry_id)
    if original.status != EntryStatus.POSTED:
        raise BusinessRuleError(
            "Seule une écriture validée se contre-passe ; un brouillon se modifie."
        )
    if original.reversal_of_id is not None:
        raise BusinessRuleError(
            "Une contre-passation ne se contre-passe pas : saisissez une nouvelle écriture."
        )
    already = session.execute(
        select(JournalEntry.id).where(
            JournalEntry.tenant_id == actor.company_id, JournalEntry.reversal_of_id == original.id
        )
    ).scalar_one_or_none()
    if already is not None:
        raise ConflictError("Cette écriture a déjà été contre-passée.")
    journal = session.get_one(Journal, original.journal_id)
    lines = session.execute(
        select(JournalLine).where(JournalLine.entry_id == original.id).order_by(JournalLine.line_no)
    ).scalars()
    data = EntryData(
        journal_id=original.journal_id,
        entry_date=reversal_date,
        label=f"Contre-passation {journal.code} n° {original.number} — {original.label}"[:200],
        reference=original.reference,
        lines=[
            LineData(
                account_id=line.account_id, debit=line.credit, credit=line.debit, label=line.label
            )
            for line in lines
        ],
    )
    reversal = JournalEntry(
        tenant_id=actor.company_id,
        created_by_user_id=actor.user_id,
        status=EntryStatus.DRAFT,
        reversal_of_id=original.id,
        # La contre-passation d'à-nouveaux générés garde leur origine.
        origin=original.origin,
    )
    _apply(session, actor, reversal, data)
    session.add(reversal)
    session.flush()
    _write_lines(session, actor, reversal, data.lines)
    session.flush()
    _post(session, actor, reversal, system=original.origin == EntryOrigin.CLOSING)
    _audit(
        session,
        actor,
        "entry.reversed",
        original.id,
        {"journal": journal.code, "numero": original.number, "contre_passation": str(reversal.id)},
    )
    if commit:
        session.commit()
    return reversal


# --- Lecture


def get_entry(session: Session, company_id: uuid.UUID, entry_id: uuid.UUID) -> EntryView:
    row = session.execute(
        select(JournalEntry, Journal)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .where(JournalEntry.id == entry_id, JournalEntry.tenant_id == company_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Écriture introuvable.")
    entry, journal = row
    lines = session.execute(
        select(JournalLine, Account)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry.id)
        .order_by(JournalLine.line_no)
    ).all()
    return EntryView(entry, journal, [(line, account) for line, account in lines])


def reversal_id_of(
    session: Session, company_id: uuid.UUID, entry_id: uuid.UUID
) -> uuid.UUID | None:
    return session.execute(
        select(JournalEntry.id).where(
            JournalEntry.tenant_id == company_id, JournalEntry.reversal_of_id == entry_id
        )
    ).scalar_one_or_none()


@dataclass(frozen=True)
class EntryFilters:
    journal_id: uuid.UUID | None = None
    fiscal_year_id: uuid.UUID | None = None
    status: EntryStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    account_id: uuid.UUID | None = None
    search: str | None = None


@dataclass(frozen=True)
class EntrySummary:
    entry: JournalEntry
    journal_code: str
    total_debit: int
    total_credit: int


def _filtered(company_id: uuid.UUID, filters: EntryFilters) -> Select[uuid.UUID]:
    query = select(JournalEntry.id).where(JournalEntry.tenant_id == company_id)
    if filters.journal_id:
        query = query.where(JournalEntry.journal_id == filters.journal_id)
    if filters.fiscal_year_id:
        query = query.where(JournalEntry.fiscal_year_id == filters.fiscal_year_id)
    if filters.status:
        query = query.where(JournalEntry.status == filters.status)
    if filters.date_from:
        query = query.where(JournalEntry.entry_date >= filters.date_from)
    if filters.date_to:
        query = query.where(JournalEntry.entry_date <= filters.date_to)
    if filters.account_id:
        query = query.where(
            select(JournalLine.id)
            .where(
                JournalLine.entry_id == JournalEntry.id,
                JournalLine.account_id == filters.account_id,
            )
            .exists()
        )
    if filters.search:
        pattern = (
            "%" + filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        query = query.where(
            JournalEntry.label.ilike(pattern, escape="\\")
            | JournalEntry.reference.ilike(pattern, escape="\\")
        )
    return query


def list_entries(
    session: Session, company_id: uuid.UUID, filters: EntryFilters, *, limit: int, offset: int
) -> tuple[list[EntrySummary], int]:
    ids = _filtered(company_id, filters).subquery()
    total = session.execute(select(func.count()).select_from(ids)).scalar_one()
    rows = session.execute(
        select(JournalEntry, Journal.code)
        .join(ids, ids.c.id == JournalEntry.id)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .order_by(
            JournalEntry.entry_date.desc(),
            Journal.code,
            JournalEntry.number.desc().nulls_first(),
            JournalEntry.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    # Totaux de la seule page affichée : une requête, quel que soit le nombre de lignes.
    page_ids = [entry.id for entry, _ in rows]
    totals = {
        entry_id: (int(debit), int(credit))
        for entry_id, debit, credit in session.execute(
            select(JournalLine.entry_id, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
            .where(JournalLine.tenant_id == company_id, JournalLine.entry_id.in_(page_ids))
            .group_by(JournalLine.entry_id)
        ).all()
    }
    return [EntrySummary(entry, code, *totals.get(entry.id, (0, 0))) for entry, code in rows], total
