"""Relevés bancaires : import, consultation, tri des lignes (sous-phase 3B).

Un relevé est importé sur un compte financier existant. L'import est atomique :
le fichier original est d'abord écrit chiffré dans le stockage, puis le relevé et
ses lignes sont enregistrés en base ; si l'enregistrement échoue, l'objet est
retiré (même ordre que les pièces justificatives : une ligne en base désigne
toujours un objet existant).

Barrières contre le double comptage :
- l'empreinte SHA-256 du fichier refuse le réimport du même relevé sur le même
  compte (contrainte en base) ;
- l'empreinte métier de chaque ligne (date, montant, libellé, référence) est
  conservée pour signaler les doublons entre relevés successifs — les relevés
  mensuels se recouvrent souvent d'un mois sur l'autre : le rapprochement (3C)
  en tirera parti plutôt que de compter deux fois l'opération.

La vérité comptable reste le grand livre : aucune écriture n'est créée à l'import.
Une ligne ne peut qu'être ignorée ou rapprochée (3C), jamais corrigée : en cas de
relevé erroné, on supprime le relevé (lignes non rapprochées uniquement) et on
réimporte un fichier corrigé.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kora.attachments.service import clean_filename
from kora.audit.service import record_event
from kora.core.config import get_settings
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError, PayloadTooLargeError
from kora.models.treasury import (
    BankStatement,
    BankStatementLine,
    FinancialAccount,
    StatementLineStatus,
)
from kora.storage import objects
from kora.treasury import parsing
from kora.treasury.service import _account

if TYPE_CHECKING:
    # Annotations seulement : le service 3A importe les modèles, pas ce module.
    from kora.accounting.entries import Actor

logger = logging.getLogger(__name__)

ACCEPTED_FORMATS = "OFX, CSV ou Excel (.xlsx)"


def too_large() -> PayloadTooLargeError:
    limit_mb = get_settings().statement_max_bytes // (1024 * 1024)
    return PayloadTooLargeError(f"Relevé trop volumineux (maximum {limit_mb} Mo).")


def storage_key(company_id: uuid.UUID, statement_id: uuid.UUID) -> str:
    return f"statements/{company_id}/{statement_id}"


@dataclass(frozen=True)
class StatementView:
    statement: BankStatement
    account_name: str


@dataclass(frozen=True)
class StatementPage:
    items: list[StatementView]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class LineRow:
    id: uuid.UUID
    line_no: int
    value_date: str
    amount: int
    label: str
    reference: str | None
    balance_after: int | None
    status: str
    # True : la même opération (date, montant, libellé, référence) figure déjà sur un
    # autre relevé du même compte — recouvrement de période ou double export.
    duplicate: bool


@dataclass(frozen=True)
class LinePage:
    statement: BankStatement
    items: list[LineRow]
    total: int
    limit: int
    offset: int


def import_statement(
    session: Session,
    actor: Actor,
    account_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> BankStatement:
    """Importe un relevé OFX ou CSV sur un compte financier : lecture, déduplication,
    conservation du fichier original, lignes en attente de rapprochement."""
    # Import tardif inutile : le service 3A ne connaît pas les relevés, l'inverse oui.
    settings = get_settings()
    if not content:
        raise BusinessRuleError("Le fichier est vide.")
    if len(content) > settings.statement_max_bytes:
        raise too_large()

    # Verrou du compte : sérialise les imports concurrents sur le même compte (deux
    # relevés importés en même temps ne doivent pas pouvoir doubler les lignes).
    account = _account(session, actor.company_id, account_id, lock=True)
    if not account.is_active:
        raise BusinessRuleError(f"Le compte « {account.name} » est désactivé.")

    parsed = parsing.parse_statement(content)
    if not parsed.lines:
        raise BusinessRuleError("Aucune opération reconnue dans ce fichier.")
    if len(parsed.lines) > settings.statement_max_lines:
        raise BusinessRuleError(
            f"Trop d'opérations dans ce relevé ({len(parsed.lines)}) : "
            f"maximum {settings.statement_max_lines}."
        )

    digest = hashlib.sha256(content).hexdigest()
    existing = session.execute(
        select(BankStatement).where(
            BankStatement.tenant_id == actor.company_id,
            BankStatement.financial_account_id == account_id,
            BankStatement.sha256 == digest,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            "Ce relevé a déjà été importé sur ce compte : le réimporter compterait "
            "les opérations deux fois."
        )

    statement_id = uuid.uuid4()
    key = storage_key(actor.company_id, statement_id)
    sealed = objects.seal(content, key)
    objects.put(key, sealed)

    dates = [line.value_date for line in parsed.lines]
    statement = BankStatement(
        id=statement_id,
        tenant_id=actor.company_id,
        financial_account_id=account.id,
        filename=clean_filename(filename),
        format=parsed.format,
        size_bytes=len(content),
        sha256=digest,
        line_count=len(parsed.lines),
        period_start=min(dates),
        period_end=max(dates),
        storage_key=key,
        wrapped_key=sealed.wrapped_key,
        uploaded_by_user_id=actor.user_id,
    )
    lines = [
        BankStatementLine(
            id=uuid.uuid4(),
            tenant_id=actor.company_id,
            statement_id=statement_id,
            line_no=no,
            value_date=line.value_date,
            amount=line.amount,
            label=line.label,
            reference=line.reference,
            balance_after=line.balance_after,
            content_hash=parsing.line_content_hash(line),
            status=StatementLineStatus.PENDING.value,
        )
        for no, line in enumerate(parsed.lines, start=1)
    ]
    try:
        session.add(statement)
        session.add_all(lines)
        session.flush()
        record_event(
            session,
            action="treasury.statement.imported",
            entity_type="bank_statement",
            entity_id=statement.id,
            payload={
                "compte_financier": account.name,
                "fichier": statement.filename,
                "format": statement.format,
                "lignes": statement.line_count,
                "periode": (
                    f"{statement.period_start.isoformat()} → {statement.period_end.isoformat()}"
                ),
                "taille_octets": statement.size_bytes,
            },
            actor_user_id=actor.user_id,
            ip_address=actor.ctx.ip_address,
        )
        session.commit()
    except BaseException:
        session.rollback()
        _purge_quietly(key)
        raise
    return statement


def _purge_quietly(key: str) -> None:
    """L'enregistrement a échoué après l'écriture du fichier : l'objet est retiré,
    sans jamais masquer l'erreur d'origine."""
    try:
        objects.delete(key)
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover - dépend du réseau
        logger.error(
            "Relevé orphelin au stockage (objet non retiré après échec)",
            extra={"objet": key, "erreur": str(exc)},
        )


def _statement(session: Session, company_id: uuid.UUID, statement_id: uuid.UUID) -> BankStatement:
    statement = session.execute(
        select(BankStatement).where(
            BankStatement.id == statement_id, BankStatement.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if statement is None:
        raise NotFoundError("Relevé introuvable.")
    return statement


def list_statements(
    session: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> StatementPage:
    """Relevés d'un compte financier, du plus récent au plus ancien."""
    account = session.execute(
        select(FinancialAccount).where(
            FinancialAccount.tenant_id == company_id, FinancialAccount.id == account_id
        )
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte financier introuvable.")
    where = (
        BankStatement.tenant_id == company_id,
        BankStatement.financial_account_id == account_id,
    )
    total = int(
        session.execute(select(func.count()).select_from(BankStatement).where(*where)).scalar_one()
    )
    rows = list(
        session.execute(
            select(BankStatement)
            .where(*where)
            .order_by(BankStatement.created_at.desc(), BankStatement.id)
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return StatementPage(
        items=[StatementView(statement=row, account_name=account.name) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def list_statement_lines(
    session: Session,
    company_id: uuid.UUID,
    statement_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> LinePage:
    """Lignes d'un relevé, dans l'ordre du fichier, avec le signalement des doublons
    (même empreinte métier déjà présente sur un autre relevé du même compte)."""
    statement = _statement(session, company_id, statement_id)

    duplicate_hashes = set(
        session.execute(
            select(BankStatementLine.content_hash)
            .join(
                BankStatement,
                (BankStatement.tenant_id == BankStatementLine.tenant_id)
                & (BankStatement.id == BankStatementLine.statement_id),
            )
            .where(
                BankStatementLine.tenant_id == company_id,
                BankStatementLine.statement_id != statement_id,
                # Seul le même compte est pertinent : la même opération sur deux
                # comptes différents n'est pas un doublon de saisie.
                BankStatement.financial_account_id == statement.financial_account_id,
                BankStatementLine.content_hash.in_(
                    select(BankStatementLine.content_hash).where(
                        BankStatementLine.tenant_id == company_id,
                        BankStatementLine.statement_id == statement_id,
                    )
                ),
            )
        ).scalars()
    )

    where = (
        BankStatementLine.tenant_id == company_id,
        BankStatementLine.statement_id == statement_id,
    )
    total = int(
        session.execute(
            select(func.count()).select_from(BankStatementLine).where(*where)
        ).scalar_one()
    )
    rows = list(
        session.execute(
            select(BankStatementLine)
            .where(*where)
            .order_by(BankStatementLine.line_no)
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    items = [
        LineRow(
            id=row.id,
            line_no=row.line_no,
            value_date=row.value_date.isoformat(),
            amount=row.amount,
            label=row.label,
            reference=row.reference,
            balance_after=row.balance_after,
            status=row.status,
            duplicate=row.content_hash in duplicate_hashes,
        )
        for row in rows
    ]
    return LinePage(statement=statement, items=items, total=total, limit=limit, offset=offset)


def _line(
    session: Session,
    company_id: uuid.UUID,
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
) -> BankStatementLine:
    line = session.execute(
        select(BankStatementLine).where(
            BankStatementLine.id == line_id,
            BankStatementLine.statement_id == statement_id,
            BankStatementLine.tenant_id == company_id,
        )
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError("Ligne de relevé introuvable.")
    return line


def set_line_status(
    session: Session,
    actor: Actor,
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    status: StatementLineStatus,
) -> BankStatementLine:
    """Ignore ou remet en attente une ligne de relevé. Le statut MATCHED n'est pas
    accessible ici : seul le rapprochement (3C) l'appose, avec l'écriture associée."""
    statement = _statement(session, actor.company_id, statement_id)
    line = _line(session, actor.company_id, statement_id, line_id)
    if status == StatementLineStatus.MATCHED:
        raise BusinessRuleError(
            "Une ligne se rapproche depuis le module de rapprochement : l'appariement "
            "direct n'est pas permis."
        )
    if line.status == StatementLineStatus.MATCHED.value:
        raise ConflictError(
            "Cette ligne est déjà rapprochée : elle ne peut plus être ignorée ni remise en attente."
        )
    if line.status == status.value:
        return line  # idempotent : répéter le même tri ne change rien
    line.status = status.value
    record_event(
        session,
        action=(
            "treasury.statement.line.ignored"
            if status == StatementLineStatus.IGNORED
            else "treasury.statement.line.restored"
        ),
        entity_type="bank_statement_line",
        entity_id=line.id,
        payload={
            "releve": statement.filename,
            "ligne": line.line_no,
            "date": line.value_date.isoformat(),
            "montant": line.amount,
            "statut": status.value,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return line


def delete_statement(session: Session, actor: Actor, statement_id: uuid.UUID) -> None:
    """Supprime un relevé et ses lignes (non rapprochées uniquement) ainsi que le
    fichier original conservé : base d'abord, objet ensuite."""
    statement = _statement(session, actor.company_id, statement_id)
    matched = session.execute(
        select(func.count())
        .select_from(BankStatementLine)
        .where(
            BankStatementLine.tenant_id == actor.company_id,
            BankStatementLine.statement_id == statement.id,
            BankStatementLine.status == StatementLineStatus.MATCHED.value,
        )
    ).scalar_one()
    if matched:
        raise ConflictError(
            "Ce relevé contient des lignes rapprochées : elles ne peuvent pas être "
            "supprimées avec lui."
        )
    filename = statement.filename
    line_count = statement.line_count
    key = statement.storage_key
    session.execute(delete(BankStatementLine).where(BankStatementLine.statement_id == statement.id))
    session.execute(
        delete(BankStatement).where(
            BankStatement.id == statement.id, BankStatement.tenant_id == actor.company_id
        )
    )
    record_event(
        session,
        action="treasury.statement.deleted",
        entity_type="bank_statement",
        entity_id=statement.id,
        payload={
            "fichier": filename,
            "lignes": line_count,
            "compte_financier": str(statement.financial_account_id),
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    try:
        objects.delete(key)
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover - dépend du réseau
        logger.error(
            "Relevé supprimé en base mais objet non retiré au stockage",
            extra={"objet": key, "erreur": str(exc)},
        )
