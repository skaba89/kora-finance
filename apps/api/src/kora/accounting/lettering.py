"""Lettrage des comptes de tiers.

Lettrer, c'est rapprocher des lignes validées d'un même compte dont la somme
(débits - crédits) est nulle : une facture et son règlement, plusieurs factures et un
paiement global… Le solde non lettré d'un compte client ou fournisseur donne ce qui
reste dû. La base vérifie elle-même l'équilibre de chaque lettrage (migration 0006).

Comptes lettrables : comptes de tiers, classe 4. À valider par un expert-comptable
guinéen (faut-il y ajouter d'autres comptes, par exemple 47 ou certains 5x ?).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account
from kora.models.ledger import (
    EntryStatus,
    Journal,
    JournalEntry,
    JournalLine,
    Lettering,
    LetteringLine,
)

LETTERABLE_CLASS = "4"

LineStatus = Literal["open", "lettered", "all"]


def lettering_code(sequence: int) -> str:
    """1 → A, 26 → Z, 27 → AA, 28 → AB… (base 26 bijective, comme un tableur)."""
    code = ""
    while sequence > 0:
        sequence, remainder = divmod(sequence - 1, 26)
        code = chr(ord("A") + remainder) + code
    return code


def _letterable_account(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, *, lock: bool = False
) -> Account:
    query = select(Account).where(Account.id == account_id, Account.tenant_id == company_id)
    account = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte introuvable.")
    if not account.number.startswith(LETTERABLE_CLASS):
        raise BusinessRuleError(
            f"Le compte {account.number} n'est pas lettrable : seuls les comptes de tiers "
            "(classe 4) se lettrent."
        )
    return account


# --- Lecture


@dataclass(frozen=True)
class LetterableLine:
    line_id: uuid.UUID
    entry_id: uuid.UUID
    entry_date: date
    journal_code: str
    number: int | None
    reference: str | None
    label: str
    debit: int
    credit: int
    lettering_id: uuid.UUID | None
    lettering_code: str | None


@dataclass(frozen=True)
class LetterableLines:
    account: Account
    lines: list[LetterableLine]
    total: int
    open_balance: int  # solde non lettré (positif = débiteur)


def list_lines(
    session: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    status: LineStatus,
    limit: int,
    offset: int,
) -> LetterableLines:
    """Lignes validées du compte, tous exercices confondus (une facture de décembre se
    lettre avec son règlement de janvier)."""
    account = _letterable_account(session, company_id, account_id)
    base = (
        select(
            JournalLine.id.label("line_id"),
            JournalEntry.id.label("entry_id"),
            JournalEntry.entry_date,
            Journal.code.label("journal_code"),
            JournalEntry.number,
            JournalEntry.reference,
            func.coalesce(JournalLine.label, JournalEntry.label).label("label"),
            JournalLine.debit,
            JournalLine.credit,
            JournalLine.line_no,
            Lettering.id.label("lettering_id"),
            Lettering.sequence,
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Journal, Journal.id == JournalEntry.journal_id)
        .outerjoin(LetteringLine, LetteringLine.line_id == JournalLine.id)
        .outerjoin(Lettering, Lettering.id == LetteringLine.lettering_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalLine.account_id == account.id,
            JournalEntry.status == EntryStatus.POSTED,
        )
    )
    if status == "open":
        base = base.where(Lettering.id.is_(None))
    elif status == "lettered":
        base = base.where(Lettering.id.is_not(None))
    filtered = base.subquery()
    total = session.execute(select(func.count()).select_from(filtered)).scalar_one()
    rows = session.execute(
        select(filtered)
        .order_by(
            filtered.c.entry_date, filtered.c.journal_code, filtered.c.number, filtered.c.line_no
        )
        .limit(limit)
        .offset(offset)
    ).all()
    open_balance = session.execute(
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .outerjoin(LetteringLine, LetteringLine.line_id == JournalLine.id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalLine.account_id == account.id,
            JournalEntry.status == EntryStatus.POSTED,
            LetteringLine.line_id.is_(None),
        )
    ).scalar_one()
    return LetterableLines(
        account=account,
        lines=[
            LetterableLine(
                line_id=r.line_id,
                entry_id=r.entry_id,
                entry_date=r.entry_date,
                journal_code=r.journal_code,
                number=r.number,
                reference=r.reference,
                label=r.label,
                debit=int(r.debit),
                credit=int(r.credit),
                lettering_id=r.lettering_id,
                lettering_code=lettering_code(r.sequence) if r.sequence else None,
            )
            for r in rows
        ],
        total=int(total),
        open_balance=int(open_balance),
    )


# --- Lettrage et délettrage


def _create(
    session: Session, actor: Actor, account: Account, line_ids: list[uuid.UUID], *, source: str
) -> Lettering:
    sequence = (
        session.execute(
            select(func.coalesce(func.max(Lettering.sequence), 0)).where(
                Lettering.tenant_id == actor.company_id, Lettering.account_id == account.id
            )
        ).scalar_one()
        + 1
    )
    lettering = Lettering(
        tenant_id=actor.company_id,
        account_id=account.id,
        sequence=sequence,
        created_by_user_id=actor.user_id,
    )
    session.add(lettering)
    session.flush()
    session.add_all(
        LetteringLine(tenant_id=actor.company_id, lettering_id=lettering.id, line_id=line_id)
        for line_id in line_ids
    )
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Une de ces lignes est déjà lettrée.") from exc
    record_event(
        session,
        action="lettering.created",
        entity_type="lettering",
        entity_id=lettering.id,
        payload={
            "compte": account.number,
            "code": lettering_code(sequence),
            "lignes": [str(i) for i in line_ids],
            "origine": source,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    return lettering


def letter(
    session: Session, actor: Actor, account_id: uuid.UUID, line_ids: list[uuid.UUID]
) -> Lettering:
    # Compte verrouillé : les lettrages d'un compte sont numérotés sans collision.
    account = _letterable_account(session, actor.company_id, account_id, lock=True)
    unique_ids = list(dict.fromkeys(line_ids))
    if len(unique_ids) < 2:
        raise BusinessRuleError("Un lettrage rapproche au moins deux lignes.")
    rows = session.execute(
        select(JournalLine, JournalEntry.status, LetteringLine.lettering_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .outerjoin(LetteringLine, LetteringLine.line_id == JournalLine.id)
        .where(JournalLine.tenant_id == actor.company_id, JournalLine.id.in_(unique_ids))
    ).all()
    if len(rows) != len(unique_ids):
        raise BusinessRuleError("Ligne introuvable dans ce dossier.")
    errors = []
    if any(line.account_id != account.id for line, _, _ in rows):
        errors.append(f"Toutes les lignes doivent être sur le compte {account.number}.")
    if any(status != EntryStatus.POSTED for _, status, _ in rows):
        errors.append("Seules les lignes d'écritures validées se lettrent.")
    if any(existing is not None for _, _, existing in rows):
        errors.append("Une de ces lignes est déjà lettrée.")
    net = sum(line.debit - line.credit for line, _, _ in rows)
    if net != 0:
        errors.append(f"Les lignes ne s'équilibrent pas (écart {net}).")
    if errors:
        raise BusinessRuleError("Lettrage impossible.", errors=errors)
    lettering = _create(session, actor, account, unique_ids, source="manuel")
    session.commit()
    return lettering


def unletter(session: Session, actor: Actor, lettering_id: uuid.UUID) -> None:
    lettering = session.execute(
        select(Lettering)
        .where(Lettering.id == lettering_id, Lettering.tenant_id == actor.company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if lettering is None:
        raise NotFoundError("Lettrage introuvable.")
    account = session.get_one(Account, lettering.account_id)
    record_event(
        session,
        action="lettering.deleted",
        entity_type="lettering",
        entity_id=lettering.id,
        payload={"compte": account.number, "code": lettering_code(lettering.sequence)},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.delete(lettering)
    session.commit()


def auto_letter_by_reference(session: Session, actor: Actor, account_id: uuid.UUID) -> int:
    """Lettre les lignes non lettrées qui partagent une même référence de pièce et
    s'équilibrent (ex. facture F-12 et règlement « F-12 »). Ne devine rien d'autre :
    les rapprochements incertains restent manuels. Renvoie le nombre de lettrages."""
    account = _letterable_account(session, actor.company_id, account_id, lock=True)
    rows = session.execute(
        select(JournalLine.id, JournalLine.debit, JournalLine.credit, JournalEntry.reference)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .outerjoin(LetteringLine, LetteringLine.line_id == JournalLine.id)
        .where(
            JournalLine.tenant_id == actor.company_id,
            JournalLine.account_id == account.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.reference.is_not(None),
            LetteringLine.line_id.is_(None),
        )
        .order_by(JournalEntry.entry_date, JournalLine.id)
    ).all()
    groups: dict[str, list[tuple[uuid.UUID, int, int]]] = defaultdict(list)
    for line_id, debit, credit, reference in rows:
        if reference and reference.strip():
            groups[reference.strip().upper()].append((line_id, debit, credit))
    created = 0
    for lines in groups.values():
        has_both_sides = any(d for _, d, _ in lines) and any(c for _, _, c in lines)
        if len(lines) >= 2 and has_both_sides and sum(d - c for _, d, c in lines) == 0:
            _create(session, actor, account, [i for i, _, _ in lines], source="automatique")
            created += 1
    session.commit()
    return created
