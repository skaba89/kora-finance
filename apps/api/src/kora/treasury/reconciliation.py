"""Rapprochement bancaire (sous-phase 3C) : proposition assistée, confirmation humaine.

Une ligne de relevé (vue de la banque) et un mouvement de trésorerie (trace
opérationnelle) décrivent souvent la même opération. Le rapprochement les relie
explicitement : la ligne passe de PENDING à MATCHED, avec le mouvement — donc
l'écriture validée — comme contrepartie.

Règle de conception, non négociable : **aucun appariement automatique**. Le moteur
propose des candidats classés par score ; un humain confirme (ou retire). Une
proposition erronée confirmée reste réversible (dé-rapprochement), ce qu'un
appariement silencieux ne permettrait pas — et le journal d'audit conserve qui,
quand et quoi.

Fenêtre conservatrice du moteur :
- même compte financier que le relevé (l'opération d'une autre banque n'est pas un
  candidat) ;
- montant **strictement égal** (|ligne| == mouvement) et direction cohérente
  (entrée de fonds ⇔ DEBIT) : un écart (agios, arrondi) se traite par un
  mouvement dédié, pas en rapprochant à moitié ;
- mouvement jamais rapproché (contrainte d'unicité en base, migration 0013) ;
- fenêtre de dates bornée (± 180 jours) : au-delà, c'est un rapprochement de
  l'année précédente, pas de ce relevé.

Le tri des verrous (ligne, puis mouvement) est toujours le même : deux
confirmations concurrentes du même mouvement se sérialisent, la seconde voit un
mouvement déjà rapproché et est refusée (la contrainte unique de la migration 0013
reste le dernier rempart).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.ledger import JournalEntry
from kora.models.treasury import (
    BankStatement,
    BankStatementLine,
    FinancialMovement,
    MovementDirection,
    StatementLineStatus,
)
from kora.treasury import statements
from kora.treasury.service import _account

# Fenêtre de recherche autour de la date de la ligne (rapprocher au-delà n'a pas
# de sens métier : les relevés mensuels se rapprochent dans leur période).
DATE_WINDOW_DAYS = 180
# Nombre maximum de candidats proposés (l'humain choisit : inutile de submerger).
MAX_CANDIDATES = 5
# Plafond de lecture avant scoring (garde-fou : un compte historique très chargé
# ne doit pas saturer la mémoire pour une proposition).
MAX_SCAN = 500


@dataclass(frozen=True)
class CandidateRow:
    """Mouvement proposé pour une ligne de relevé, avec son score de ressemblance."""

    id: uuid.UUID
    kind: str
    direction: str
    amount: int
    movement_date: str
    label: str
    entry_number: int | None
    days_apart: int
    score: int


@dataclass(frozen=True)
class LineCandidates:
    line_id: uuid.UUID
    line_no: int
    value_date: str
    amount: int
    label: str
    candidates: list[CandidateRow]


def _coherent_direction(line_amount: int, movement_direction: str) -> bool:
    """Entrée de fonds (ligne positive) ⇔ DEBIT ; sortie ⇔ CREDIT."""
    expected = MovementDirection.DEBIT.value if line_amount > 0 else MovementDirection.CREDIT.value
    return movement_direction == expected


def _score(
    line_date: date, line_label: str, movement_date: date, movement_label: str
) -> tuple[int, int]:
    """Score de ressemblance (plus grand = plus probable) et écart en jours."""
    days_apart = abs((movement_date - line_date).days)
    if days_apart == 0:
        score = 30
    elif days_apart <= 3:
        score = 18
    elif days_apart <= 7:
        score = 8
    else:
        score = 0
    # Un mot significatif commun (≥ 4 caractères) entre les deux libellés : la
    # banque et l'utilisateur nomment souvent la même chose autrement.
    stop = {"versement", "virement", "retrait", "depot", "dépot", "paiement", "releve"}
    words_line = {w.lower() for w in line_label.split() if len(w) >= 4 and w.lower() not in stop}
    words_movement = {
        w.lower() for w in movement_label.split() if len(w) >= 4 and w.lower() not in stop
    }
    if words_line & words_movement:
        score += 10
    return score, days_apart


def propose_candidates(
    session: Session,
    company_id: uuid.UUID,
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
) -> LineCandidates:
    """Candidats d'une ligne PENDING : mouvements du même compte, montant égal,
    direction cohérente, jamais rapprochés — classés, jamais appliqués."""
    statement = statements._statement(session, company_id, statement_id)
    line = statements._line(session, company_id, statement_id, line_id)
    if line.status == StatementLineStatus.MATCHED.value:
        raise ConflictError("Cette ligne est déjà rapprochée.")
    if line.status == StatementLineStatus.IGNORED.value:
        raise BusinessRuleError(
            "Cette ligne est écartée : remettez-la en attente pour la rapprocher."
        )

    matched_ids = (
        select(BankStatementLine.matched_movement_id).where(
            BankStatementLine.tenant_id == company_id,
            BankStatementLine.status == StatementLineStatus.MATCHED.value,
            BankStatementLine.matched_movement_id.is_not(None),
        )
    ).scalar_subquery()
    entry_number = (
        select(JournalEntry.number)
        .where(
            JournalEntry.tenant_id == company_id,
            JournalEntry.id == FinancialMovement.entry_id,
        )
        .correlate(FinancialMovement)
        .scalar_subquery()
        .label("entry_number")
    )
    rows = list(
        session.execute(
            select(
                FinancialMovement.id,
                FinancialMovement.kind,
                FinancialMovement.direction,
                FinancialMovement.amount,
                FinancialMovement.movement_date,
                FinancialMovement.label,
                entry_number,
            )
            .where(
                FinancialMovement.tenant_id == company_id,
                FinancialMovement.financial_account_id == statement.financial_account_id,
                FinancialMovement.amount == abs(line.amount),
                FinancialMovement.movement_date
                >= line.value_date - timedelta(days=DATE_WINDOW_DAYS),
                FinancialMovement.movement_date
                <= line.value_date + timedelta(days=DATE_WINDOW_DAYS),
                FinancialMovement.id.not_in(matched_ids),
            )
            .order_by(FinancialMovement.movement_date, FinancialMovement.id)
            .limit(MAX_SCAN)
        ).all()
    )
    scored: list[CandidateRow] = []
    for row in rows:
        if not _coherent_direction(line.amount, row.direction):
            continue
        score, days = _score(line.value_date, line.label, row.movement_date, row.label)
        scored.append(
            CandidateRow(
                id=row.id,
                kind=row.kind,
                direction=row.direction,
                amount=row.amount,
                movement_date=row.movement_date.isoformat(),
                label=row.label,
                entry_number=row.entry_number,
                days_apart=days,
                score=score,
            )
        )
    scored.sort(key=lambda c: (-c.score, c.days_apart, c.movement_date, str(c.id)))
    return LineCandidates(
        line_id=line.id,
        line_no=line.line_no,
        value_date=line.value_date.isoformat(),
        amount=line.amount,
        label=line.label,
        candidates=scored[:MAX_CANDIDATES],
    )


def confirm_match(
    session: Session,
    actor: Actor,
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    movement_id: uuid.UUID,
) -> BankStatementLine:
    """Rapproche une ligne PENDING d'un mouvement : statut MATCHED, contrepartie
    posée, audit tracé. La confirmation est explicite : le moteur ne pose jamais
    ce lien de lui-même."""
    statement = statements._statement(session, actor.company_id, statement_id)
    # Verrou de la ligne d'abord, puis du mouvement (ordre unique dans ce module).
    line = session.execute(
        select(BankStatementLine)
        .where(
            BankStatementLine.id == line_id,
            BankStatementLine.statement_id == statement_id,
            BankStatementLine.tenant_id == actor.company_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError("Ligne de relevé introuvable.")
    movement = session.execute(
        select(FinancialMovement)
        .where(
            FinancialMovement.id == movement_id,
            FinancialMovement.tenant_id == actor.company_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if movement is None:
        raise NotFoundError("Mouvement introuvable.")

    if line.status == StatementLineStatus.MATCHED.value:
        raise ConflictError("Cette ligne est déjà rapprochée : retirez d'abord son appariement.")
    if line.status == StatementLineStatus.IGNORED.value:
        raise BusinessRuleError(
            "Cette ligne est écartée : remettez-la en attente pour la rapprocher."
        )
    if movement.financial_account_id != statement.financial_account_id:
        raise BusinessRuleError(
            "Ce mouvement appartient à un autre compte financier que le relevé : "
            "l'appariement est refusé."
        )
    if movement.amount != abs(line.amount):
        raise BusinessRuleError(
            "Le montant du mouvement ne correspond pas à la ligne du relevé : "
            "l'écart se traite par un mouvement dédié, pas par un rapprochement forcé."
        )
    if not _coherent_direction(line.amount, movement.direction):
        raise BusinessRuleError(
            "La direction du mouvement ne correspond pas au sens de la ligne du relevé."
        )
    other = session.execute(
        select(func.count())
        .select_from(BankStatementLine)
        .where(
            BankStatementLine.tenant_id == actor.company_id,
            BankStatementLine.status == StatementLineStatus.MATCHED.value,
            BankStatementLine.matched_movement_id == movement.id,
            BankStatementLine.id != line.id,
        )
    ).scalar_one()
    if other:
        raise ConflictError(
            "Ce mouvement est déjà rapproché d'une autre ligne : chaque opération "
            "ne peut être comptée qu'une fois."
        )

    line.status = StatementLineStatus.MATCHED.value
    line.matched_movement_id = movement.id
    try:
        record_event(
            session,
            action="treasury.reconciliation.matched",
            entity_type="bank_statement_line",
            entity_id=line.id,
            payload={
                "releve": statement.filename,
                "ligne": line.line_no,
                "date_ligne": line.value_date.isoformat(),
                "montant_ligne": line.amount,
                "mouvement": str(movement.id),
                "type_mouvement": movement.kind,
                "date_mouvement": movement.movement_date.isoformat(),
                "montant_mouvement": movement.amount,
                "ecriture": str(movement.entry_id),
            },
            actor_user_id=actor.user_id,
            ip_address=actor.ctx.ip_address,
        )
        session.commit()
    except IntegrityError as exc:
        # Deux confirmations concurrentes du même mouvement : la contrainte unique
        # (migration 0013) tranche, la seconde est refusée proprement.
        session.rollback()
        raise ConflictError(
            "Ce mouvement vient d'être rapproché par une autre ligne : "
            "une seule ligne peut désigner un mouvement."
        ) from exc
    return line


def unmatch_line(
    session: Session,
    actor: Actor,
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
) -> BankStatementLine:
    """Retire le rapprochement d'une ligne : elle repasse en attente, le mouvement
    redevient disponible. Réversible par conception : une confirmation erronée ne
    doit jamais être définitive."""
    statement = statements._statement(session, actor.company_id, statement_id)
    line = session.execute(
        select(BankStatementLine)
        .where(
            BankStatementLine.id == line_id,
            BankStatementLine.statement_id == statement_id,
            BankStatementLine.tenant_id == actor.company_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError("Ligne de relevé introuvable.")
    if line.status != StatementLineStatus.MATCHED.value:
        raise ConflictError("Cette ligne n'est pas rapprochée.")
    movement_id = line.matched_movement_id
    line.status = StatementLineStatus.PENDING.value
    line.matched_movement_id = None
    record_event(
        session,
        action="treasury.reconciliation.unmatched",
        entity_type="bank_statement_line",
        entity_id=line.id,
        payload={
            "releve": statement.filename,
            "ligne": line.line_no,
            "mouvement": str(movement_id) if movement_id else None,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return line


@dataclass(frozen=True)
class ReconciliationOverview:
    account_id: uuid.UUID
    lines_pending: int
    lines_matched: int
    lines_ignored: int
    # Somme signée des lignes à rapprocher : ce que le relevé attend encore
    # d'explications (écarts, opérations non saisies, doublons).
    pending_net: int
    # Mouvements du compte jamais rapprochés : candidats encore disponibles.
    movements_unmatched: int


def reconciliation_overview(
    session: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
) -> ReconciliationOverview:
    """Vue d'ensemble du rapprochement d'un compte : compteurs par statut, solde
    des lignes en attente, mouvements restés sans ligne."""
    account = session.execute(
        select(BankStatement.financial_account_id)
        .where(
            BankStatement.tenant_id == company_id,
            BankStatement.financial_account_id == account_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if account is None:
        # Aucun relevé : le compte peut exister ou non — l'API répond avec des zéros
        # si le compte existe, 404 sinon (vérifié par une lecture du compte).
        _account(session, company_id, account_id, lock=False)
        return ReconciliationOverview(
            account_id=account_id,
            lines_pending=0,
            lines_matched=0,
            lines_ignored=0,
            pending_net=0,
            movements_unmatched=0,
        )

    counts = dict(
        session.execute(
            select(BankStatementLine.status, func.count())
            .join(
                BankStatement,
                (BankStatement.tenant_id == BankStatementLine.tenant_id)
                & (BankStatement.id == BankStatementLine.statement_id),
            )
            .where(
                BankStatementLine.tenant_id == company_id,
                BankStatement.financial_account_id == account_id,
            )
            .group_by(BankStatementLine.status)
        ).all()
    )
    pending_net = int(
        session.execute(
            select(func.coalesce(func.sum(BankStatementLine.amount), 0))
            .join(
                BankStatement,
                (BankStatement.tenant_id == BankStatementLine.tenant_id)
                & (BankStatement.id == BankStatementLine.statement_id),
            )
            .where(
                BankStatementLine.tenant_id == company_id,
                BankStatement.financial_account_id == account_id,
                BankStatementLine.status == StatementLineStatus.PENDING.value,
            )
        ).scalar_one()
    )
    matched_ids = (
        select(BankStatementLine.matched_movement_id).where(
            BankStatementLine.tenant_id == company_id,
            BankStatementLine.status == StatementLineStatus.MATCHED.value,
            BankStatementLine.matched_movement_id.is_not(None),
        )
    ).scalar_subquery()
    movements_unmatched = int(
        session.execute(
            select(func.count())
            .select_from(FinancialMovement)
            .where(
                FinancialMovement.tenant_id == company_id,
                FinancialMovement.financial_account_id == account_id,
                FinancialMovement.id.not_in(matched_ids),
            )
        ).scalar_one()
    )
    return ReconciliationOverview(
        account_id=account_id,
        lines_pending=int(counts.get(StatementLineStatus.PENDING.value, 0)),
        lines_matched=int(counts.get(StatementLineStatus.MATCHED.value, 0)),
        lines_ignored=int(counts.get(StatementLineStatus.IGNORED.value, 0)),
        pending_net=pending_net,
        movements_unmatched=movements_unmatched,
    )
