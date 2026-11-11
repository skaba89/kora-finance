"""Trésorerie : comptes financiers et mouvements (sous-phase 3A).

Un compte financier (banque, caisse, portefeuille Mobile Money) est le miroir
opérationnel d'un compte du plan comptable : son solde n'est jamais stocké, il est
recalculé depuis les lignes validées du compte lié. Le grand livre reste la seule
source de vérité — le TFT et la balance ne peuvent pas diverger de la trésorerie.

Chaque mouvement crée, dans une même transaction, une écriture validée du journal de
trésorerie (BQ pour une banque, CA pour une caisse, MM pour Mobile Money) et sa trace
opérationnelle (`financial_movements`). Le compte de contrepartie (capital, ventes,
charges…) est toujours fourni : la trésorerie n'invente jamais une contrepartie
comptable. Les mouvements sont immuables (déclencheur, migration 0011) : une erreur
se corrige par un mouvement inverse.

Concurrence : chaque opération prend un verrou de ligne sur le compte financier
(`FOR UPDATE`) avant de valider l'écriture ; un virement verrouille les deux comptes
dans l'ordre de leurs identifiants, ce qui exclut tout interblocage. L'ordre global
des verrous (compte financier → exercice → séquence de journal) n'est pris par aucun
autre chemin applicatif, qui ne verrouillent jamais `financial_accounts`.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import (
    Actor,
    EntryData,
    LineData,
    apply_generated,
    check_entry_date,
    post_pending,
)
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalKind, JournalLine
from kora.models.treasury import (
    FinancialAccount,
    FinancialAccountKind,
    FinancialMovement,
    MovementDirection,
)

# Code du journal de trésorerie attendu pour chaque type de compte (journaux par
# défaut du dossier). Repli : premier journal de trésorerie actif par code croissant,
# si le journal attendu a été désactivé ou renommé.
_JOURNAL_BY_KIND: dict[str, str] = {
    FinancialAccountKind.BANQUE.value: "BQ",
    FinancialAccountKind.CAISSE.value: "CA",
    FinancialAccountKind.MOBILE_MONEY.value: "MM",
}

# Classe du plan comptable qui peut porter le solde d'un compte financier.
# À valider par un expert-comptable (un portefeuille Mobile Money est traité comme
# une banque électronique : classe 52 ; une caisse : 57).
_GL_PREFIX_BY_KIND: dict[str, tuple[str, ...]] = {
    FinancialAccountKind.BANQUE.value: ("52",),
    FinancialAccountKind.CAISSE.value: ("57",),
    FinancialAccountKind.MOBILE_MONEY.value: ("52",),
}


@dataclass(frozen=True)
class AccountData:
    name: str
    kind: str
    gl_account_id: uuid.UUID
    operator: str | None = None
    account_number_masked: str | None = None


@dataclass(frozen=True)
class MovementData:
    kind: str
    amount: int
    movement_date: date
    label: str
    counterpart_account_id: uuid.UUID
    reference: str | None = None


@dataclass(frozen=True)
class TransferData:
    amount: int
    movement_date: date
    label: str
    reference: str | None = None


@dataclass(frozen=True)
class AccountView:
    account: FinancialAccount
    gl_account_number: str
    gl_account_label: str
    # Solde du compte comptable lié, toutes écritures validées confondues
    # (positif = débiteur, convention de trésorerie).
    balance: int


@dataclass(frozen=True)
class MovementRow:
    id: uuid.UUID
    kind: str
    direction: str
    amount: int
    movement_date: date
    label: str
    counterpart_number: str | None
    counterpart_label: str | None
    entry_id: uuid.UUID
    entry_number: int | None
    created_at: str


@dataclass(frozen=True)
class MovementPage:
    account: FinancialAccount
    balance: int
    items: list[MovementRow]
    total: int


# --- Contrôles


def _account(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, *, lock: bool
) -> FinancialAccount:
    """Compte financier du dossier ; `lock` sérialise les mouvements concurrents."""
    query = select(FinancialAccount).where(
        FinancialAccount.id == account_id, FinancialAccount.tenant_id == company_id
    )
    account = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte financier introuvable.")
    return account


def _gl_account(session: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.tenant_id == company_id)
    ).scalar_one_or_none()
    if account is None:
        raise BusinessRuleError("Compte introuvable dans le plan comptable du dossier.")
    return account


def _active_accounts(
    session: Session, company_id: uuid.UUID, ids: set[uuid.UUID]
) -> dict[uuid.UUID, Account]:
    found = {
        a.id: a
        for a in session.execute(
            select(Account).where(Account.tenant_id == company_id, Account.id.in_(ids))
        ).scalars()
    }
    missing = ids - found.keys()
    if missing:
        raise BusinessRuleError("Compte introuvable dans le plan comptable du dossier.")
    inactive = sorted(a.number for a in found.values() if not a.is_active)
    if inactive:
        raise BusinessRuleError("Comptes désactivés : " + ", ".join(inactive) + ".")
    grouping = [a.number for a in found.values() if _has_subaccounts(session, company_id, a)]
    if grouping:
        raise BusinessRuleError(
            "Ces comptes ont des sous-comptes : choisissez un sous-compte.",
            errors=[f"Compte {n}" for n in grouping],
        )
    return found


def _has_subaccounts(session: Session, company_id: uuid.UUID, account: Account) -> bool:
    """Un compte de regroupement (ayant des sous-comptes) ne peut pas porter un solde."""
    if account.reference is None:
        return False  # un sous-compte créé par le dossier ne peut pas regrouper
    subaccounts = session.execute(
        select(func.count())
        .select_from(Account)
        .where(
            Account.tenant_id == company_id,
            Account.number.startswith(account.number),
            Account.number != account.number,
        )
    ).scalar_one()
    return subaccounts > 0


def _treasury_journal(session: Session, company_id: uuid.UUID, kind: str) -> Journal:
    """Journal de trésorerie du dossier : celui attendu pour le type de compte, ou à
    défaut le premier journal de trésorerie actif par code croissant."""
    journals = list(
        session.execute(
            select(Journal).where(
                Journal.tenant_id == company_id,
                Journal.kind == JournalKind.TRESORERIE.value,
                Journal.is_active.is_(True),
            )
        ).scalars()
    )
    expected = _JOURNAL_BY_KIND[kind]
    for journal in journals:
        if journal.code == expected:
            return journal
    if journals:
        return min(journals, key=lambda j: j.code)
    raise BusinessRuleError(
        "Aucun journal de trésorerie actif dans le dossier : créez-en un (paramètres)."
    )


def _posted_balance(session: Session, company_id: uuid.UUID, gl_account_id: uuid.UUID) -> int:
    """Somme (débits - crédits) des lignes validées du compte comptable lié."""
    return int(
        session.execute(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0)).where(
                JournalLine.tenant_id == company_id,
                JournalLine.account_id == gl_account_id,
                JournalEntry.tenant_id == company_id,
                JournalEntry.id == JournalLine.entry_id,
                JournalEntry.status == EntryStatus.POSTED.value,
            )
        ).scalar_one()
    )


def _new_entry(session: Session, actor: Actor, label: str) -> JournalEntry:
    return JournalEntry(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        label=label,
        created_by_user_id=actor.user_id,
    )


# --- Lecture


def list_accounts(session: Session, company_id: uuid.UUID) -> list[AccountView]:
    accounts = list(
        session.execute(
            select(FinancialAccount)
            .where(FinancialAccount.tenant_id == company_id)
            .order_by(FinancialAccount.kind, FinancialAccount.name)
        ).scalars()
    )
    gl_ids = {account.gl_account_id for account in accounts}
    gl = {
        a.id: a
        for a in session.execute(
            select(Account).where(Account.tenant_id == company_id, Account.id.in_(gl_ids))
        ).scalars()
    }
    views = []
    for account in accounts:
        gl_account = gl.get(account.gl_account_id)
        views.append(
            AccountView(
                account=account,
                gl_account_number=gl_account.number if gl_account else "?",
                gl_account_label=gl_account.label if gl_account else "",
                balance=_posted_balance(session, company_id, account.gl_account_id),
            )
        )
    return views


def get_account(session: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> AccountView:
    account = _account(session, company_id, account_id, lock=False)
    gl_account = _gl_account(session, company_id, account.gl_account_id)
    return AccountView(
        account=account,
        gl_account_number=gl_account.number,
        gl_account_label=gl_account.label,
        balance=_posted_balance(session, company_id, account.gl_account_id),
    )


def list_movements(
    session: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> MovementPage:
    view = get_account(session, company_id, account_id)
    counterpart_number = (
        select(Account.number)
        .where(
            Account.tenant_id == company_id, Account.id == FinancialMovement.counterpart_account_id
        )
        .correlate(FinancialMovement)
        .scalar_subquery()
        .label("counterpart_number")
    )
    counterpart_label = (
        select(Account.label)
        .where(
            Account.tenant_id == company_id, Account.id == FinancialMovement.counterpart_account_id
        )
        .correlate(FinancialMovement)
        .scalar_subquery()
        .label("counterpart_label")
    )
    entry_number = (
        select(JournalEntry.number)
        .where(JournalEntry.tenant_id == company_id, JournalEntry.id == FinancialMovement.entry_id)
        .correlate(FinancialMovement)
        .scalar_subquery()
        .label("entry_number")
    )
    base = select(
        FinancialMovement.id,
        FinancialMovement.kind,
        FinancialMovement.direction,
        FinancialMovement.amount,
        FinancialMovement.movement_date,
        FinancialMovement.label,
        FinancialMovement.entry_id,
        FinancialMovement.created_at,
        counterpart_number,
        counterpart_label,
        entry_number,
    ).where(
        FinancialMovement.tenant_id == company_id,
        FinancialMovement.financial_account_id == account_id,
    )
    total = int(
        session.execute(
            select(func.count())
            .select_from(FinancialMovement)
            .where(
                FinancialMovement.tenant_id == company_id,
                FinancialMovement.financial_account_id == account_id,
            )
        ).scalar_one()
    )
    rows = session.execute(
        base.order_by(
            FinancialMovement.movement_date, FinancialMovement.created_at, FinancialMovement.id
        )
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        MovementRow(
            id=row.id,
            kind=row.kind,
            direction=row.direction,
            amount=row.amount,
            movement_date=row.movement_date,
            label=row.label,
            counterpart_number=row.counterpart_number,
            counterpart_label=row.counterpart_label,
            entry_id=row.entry_id,
            entry_number=row.entry_number,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return MovementPage(account=view.account, balance=view.balance, items=items, total=total)


# --- Écriture des comptes


def create_account(session: Session, actor: Actor, data: AccountData) -> FinancialAccount:
    kind = data.kind
    if kind not in _GL_PREFIX_BY_KIND:
        raise BusinessRuleError("Type de compte financier inconnu.")
    if kind == FinancialAccountKind.MOBILE_MONEY.value and not data.operator:
        raise BusinessRuleError(
            "Un portefeuille Mobile Money exige un opérateur (ex. ORANGE_MONEY_GN)."
        )
    if kind != FinancialAccountKind.MOBILE_MONEY.value and data.operator:
        raise BusinessRuleError("Seul un portefeuille Mobile Money porte un opérateur.")
    gl_account = _gl_account(session, actor.company_id, data.gl_account_id)
    prefixes = _GL_PREFIX_BY_KIND[kind]
    if not gl_account.number.startswith(prefixes):
        attendus = " ou ".join(f"{p}x" for p in prefixes)
        raise BusinessRuleError(
            f"Le compte {gl_account.number} ne peut pas porter un compte de type {kind} : "
            f"choisissez un compte de classe {attendus}."
        )
    if not gl_account.is_active:
        raise BusinessRuleError(f"Le compte {gl_account.number} est désactivé.")
    account = FinancialAccount(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        name=data.name.strip(),
        kind=kind,
        operator=data.operator,
        account_number_masked=(data.account_number_masked or "").strip() or None,
        gl_account_id=data.gl_account_id,
        created_by_user_id=actor.user_id,
    )
    session.add(account)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Un compte financier porte déjà ce nom dans ce dossier.") from exc
    record_event(
        session,
        action="treasury.account.created",
        entity_type="financial_account",
        entity_id=account.id,
        payload={
            "nom": account.name,
            "type": kind,
            "operateur": account.operator,
            "compte": gl_account.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return account


# --- Mouvements


def record_movement(
    session: Session, actor: Actor, account_id: uuid.UUID, data: MovementData
) -> FinancialMovement:
    """Dépôt, retrait ou frais bancaires : une écriture validée + une trace immuable."""
    # Verrou du compte : les mouvements concurrents sur le même compte se sérialisent.
    account = _account(session, actor.company_id, account_id, lock=True)
    if not account.is_active:
        raise BusinessRuleError(f"Le compte « {account.name} » est désactivé.")
    counterpart = _active_accounts(session, actor.company_id, {data.counterpart_account_id})[
        data.counterpart_account_id
    ]
    check_entry_date(session, actor.company_id, data.movement_date)
    journal = _treasury_journal(session, actor.company_id, account.kind)

    entry = _new_entry(session, actor, data.label.strip())
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=journal.id,
            entry_date=data.movement_date,
            label=data.label.strip(),
            reference=data.reference,
            lines=_movement_lines(account, counterpart, data),
        ),
    )
    post_pending(session, actor, entry)

    direction = (
        MovementDirection.DEBIT.value if data.kind == "DEPOT" else MovementDirection.CREDIT.value
    )
    movement = FinancialMovement(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        financial_account_id=account.id,
        kind=data.kind,
        direction=direction,
        amount=data.amount,
        movement_date=data.movement_date,
        label=data.label.strip(),
        counterpart_account_id=data.counterpart_account_id,
        entry_id=entry.id,
        created_by_user_id=actor.user_id,
    )
    session.add(movement)
    session.flush()
    record_event(
        session,
        action="treasury.movement.recorded",
        entity_type="financial_movement",
        entity_id=movement.id,
        payload={
            "type": data.kind,
            "sens": direction,
            "montant": data.amount,
            "date": data.movement_date.isoformat(),
            "compte_financier": account.name,
            "contrepartie": counterpart.number,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return movement


def _movement_lines(
    account: FinancialAccount, counterpart: Account, data: MovementData
) -> list[LineData]:
    """Dépôt : débit trésorerie, crédit contrepartie. Retrait ou frais : l'inverse."""
    if data.kind == "DEPOT":
        return [
            LineData(account_id=account.gl_account_id, debit=data.amount, label=data.label.strip()),
            LineData(account_id=counterpart.id, credit=data.amount, label=data.label.strip()),
        ]
    return [
        LineData(account_id=account.gl_account_id, credit=data.amount, label=data.label.strip()),
        LineData(account_id=counterpart.id, debit=data.amount, label=data.label.strip()),
    ]


def record_transfer(
    session: Session,
    actor: Actor,
    source_account_id: uuid.UUID,
    target_account_id: uuid.UUID,
    data: TransferData,
) -> tuple[FinancialMovement, FinancialMovement]:
    """Virement interne : une écriture, deux mouvements liés (crédit source, débit cible)."""
    if source_account_id == target_account_id:
        raise BusinessRuleError("Le virement interne exige deux comptes différents.")
    # Verrous pris dans l'ordre des identifiants : aucun interblocage possible entre
    # virements concurrents, ni avec un mouvement simple (qui ne verrouille qu'un
    # compte en premier).
    first_id, second_id = sorted((source_account_id, target_account_id))
    first = _account(session, actor.company_id, first_id, lock=True)
    second = _account(session, actor.company_id, second_id, lock=True)
    source = first if first.id == source_account_id else second
    target = first if first.id == target_account_id else second
    if not source.is_active or not target.is_active:
        raise BusinessRuleError("Les deux comptes du virement doivent être actifs.")
    check_entry_date(session, actor.company_id, data.movement_date)
    journal = _treasury_journal(session, actor.company_id, source.kind)

    entry = _new_entry(session, actor, data.label.strip())
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=journal.id,
            entry_date=data.movement_date,
            label=data.label.strip(),
            reference=data.reference,
            lines=[
                LineData(
                    account_id=target.gl_account_id, debit=data.amount, label=data.label.strip()
                ),
                LineData(
                    account_id=source.gl_account_id,
                    credit=data.amount,
                    label=data.label.strip(),
                ),
            ],
        ),
    )
    post_pending(session, actor, entry)

    source_movement = FinancialMovement(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        financial_account_id=source.id,
        kind="VIREMENT_INTERNE",
        direction="CREDIT",
        amount=data.amount,
        movement_date=data.movement_date,
        label=data.label.strip(),
        entry_id=entry.id,
        created_by_user_id=actor.user_id,
    )
    target_movement = FinancialMovement(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        financial_account_id=target.id,
        kind="VIREMENT_INTERNE",
        direction="DEBIT",
        amount=data.amount,
        movement_date=data.movement_date,
        label=data.label.strip(),
        entry_id=entry.id,
        created_by_user_id=actor.user_id,
    )
    source_movement.opposite_movement_id = target_movement.id
    target_movement.opposite_movement_id = source_movement.id
    session.add_all([source_movement, target_movement])
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("Virement interne : liaison impossible entre les mouvements.") from exc
    record_event(
        session,
        action="treasury.transfer.recorded",
        entity_type="financial_movement",
        entity_id=source_movement.id,
        payload={
            "type": "VIREMENT_INTERNE",
            "montant": data.amount,
            "date": data.movement_date.isoformat(),
            "source": source.name,
            "destination": target.name,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return source_movement, target_movement
