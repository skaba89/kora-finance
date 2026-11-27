"""Confirmation humaine d'un import : génération transactionnelle de brouillons.

Le précontrôle ne crée jamais d'écriture ; la confirmation est le seul chemin
qui en crée, à la demande explicite d'un utilisateur autorisé :
- tout ou rien : les brouillons, leurs liens de traçabilité, les marqueurs du
  batch et la trace d'audit sont écrits dans **une seule** transaction ;
- jamais validé automatiquement : les écritures naissent en DRAFT, sans numéro ;
  la numérotation reste l'acte métier de la validation manuelle ;
- idempotent : le verrou de ligne du batch et le marqueur de confirmation
  rendent tout double appel inopérant (409), aucun doublon ne peut naître ;
- références revérifiées au moment décisif : le catalogue (journaux actifs,
  comptes actifs et imputables, exercice ouvert et non verrouillé) est relu
  dans la transaction d'écriture, pas celui du précontrôle.

Le fichier chiffré est redéchiffré et relu avant la transaction : aucun parsing
ne retient de connexion. Le contenu est adressé par son empreinte : il ne peut
pas changer entre la lecture et l'écriture.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor, EntryData, LineData, create_draft
from kora.accounting.import_business import MAX_CSV_BYTES
from kora.accounting.import_fec import validate_fec
from kora.accounting.import_service import _catalog
from kora.accounting.import_storage import StagedContent, _check_rate, load_staged_content
from kora.accounting.import_validation import (
    ImportIssue,
    ImportLine,
    ImportReport,
    validate_normalized_csv,
)
from kora.accounting.import_xlsx import validate_xlsx
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.accounting import Account
from kora.models.common import utcnow
from kora.models.identity import Company, User
from kora.models.imports import ImportBatch, ImportBatchEntry
from kora.models.ledger import Journal
from kora.tenancy.access import resolve_role
from kora.tenancy.permissions import Permission, permissions_for

_LINE_ERROR_LIMIT = 10


@dataclass
class _GroupDraft:
    """Écriture à créer : un groupe (journal, identifiant source) du fichier."""

    journal: str
    source: str
    day: date
    label: str
    lines: list[ImportLine] = field(default_factory=list)


@dataclass(frozen=True)
class ImportConfirmation:
    """Résultat borné d'une confirmation : des comptes, jamais le contenu."""

    batch_id: uuid.UUID
    confirmed_at: datetime
    entries: int
    lines: int
    debit: int
    credit: int


def _authorize(session: Session, user: User, company_id: uuid.UUID, currency: str) -> None:
    bind_tenant(session, company_id)
    role = resolve_role(session, user, company_id)
    if role is None:
        raise NotFoundError("Dossier introuvable.")
    if Permission.ENTRIES_WRITE not in permissions_for(role):
        raise ForbiddenError("Votre rôle ne permet pas cette action.")
    found = session.execute(
        select(Company.currency).where(Company.id == company_id)
    ).scalar_one_or_none()
    if found is None:
        raise NotFoundError("Dossier introuvable.")
    if found != currency:
        raise BusinessRuleError("La devise de l'import ne correspond plus au dossier.")


def _parse_and_collect(
    staged: StagedContent, collect: Callable[[ImportLine], None]
) -> ImportReport:
    """Analyse pure du fichier déchiffré, sans accès au tenant : la structure du
    précontrôle (mêmes analyseurs, FEC à l'échelle 0), les lignes valides remontées
    groupées par écriture."""
    if staged.file_format == "csv":
        if len(staged.content) > MAX_CSV_BYTES:
            return ImportReport(issues=[ImportIssue(1, "file_size_limit")])
        try:
            stream = StringIO(staged.content.decode("utf-8-sig"), newline="")
        except UnicodeError:
            return ImportReport(issues=[ImportIssue(1, "invalid_encoding")])
        return validate_normalized_csv(stream, on_line=collect)
    if staged.file_format == "fec":
        return validate_fec(
            staged.content, scale=0, delimiter=staged.fec_delimiter, on_line=collect
        )
    if staged.file_format == "xlsx":
        return validate_xlsx(staged.content, on_line=collect)
    return ImportReport(issues=[ImportIssue(1, "invalid_format_options")])


def _confirmable_report(groups: dict[tuple[str, str], _GroupDraft], report: ImportReport) -> None:
    """Refuse tout fichier non parfaitement propre : tout ou rien, sans import partiel."""
    if report.issues or not report.valid:
        samples = [
            f"ligne {issue.row} : {issue.code}" for issue in report.issues[:_LINE_ERROR_LIMIT]
        ]
        raise BusinessRuleError(
            "Le fichier contient des anomalies : corrigez-le et déposez-le à nouveau.",
            errors=samples,
        )
    for group in groups.values():
        debit = sum(line.debit for line in group.lines)
        credit = sum(line.credit for line in group.lines)
        if debit != credit or len(group.lines) < 2:
            # Défense en profondeur : la validation ne devrait jamais y arriver.
            raise BusinessRuleError(
                f"L'écriture « {group.source} » n'est pas équilibrée : import refusé."
            )


def confirm_staged_import(
    user: User, company_id: uuid.UUID, batch_id: uuid.UUID, *, actor: Actor
) -> ImportConfirmation:
    """Confirme le batch : brouillons + traçabilité + audit en une transaction."""
    _check_rate(user.id, company_id, "confirm")
    # Réautorise et contrôle l'intégrité du fichier ; hors transaction d'écriture.
    staged = load_staged_content(user, company_id, batch_id)

    groups: dict[tuple[str, str], _GroupDraft] = {}

    def collect(line: ImportLine) -> None:
        key = (line.journal, line.entry)
        group = groups.get(key)
        if group is None:
            groups[key] = _GroupDraft(
                journal=line.journal,
                source=line.entry,
                day=line.day,
                label=line.label,
                lines=[line],
            )
        else:
            group.lines.append(line)

    report = _parse_and_collect(staged, collect)
    _confirmable_report(groups, report)

    with get_sessionmaker()() as session, session.begin():
        _authorize(session, user, company_id, staged.currency)
        batch = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == company_id, ImportBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None or batch.expires_at <= utcnow():
            raise NotFoundError("Import introuvable ou expiré.")
        if batch.confirmed_at is not None:
            raise ConflictError("Cet import a déjà été confirmé.")
        # Référentiel relu sous le verrou : l'état au moment décisif fait foi.
        live = _catalog(session, company_id)
        stale: list[ImportIssue] = []
        for group in groups.values():
            for line in group.lines:
                stale.extend(live.check(line))
        if stale:
            samples = [f"ligne {issue.row} : {issue.code}" for issue in stale[:_LINE_ERROR_LIMIT]]
            raise BusinessRuleError(
                "Le référentiel a changé depuis le dépôt : relancez le précontrôle.",
                errors=samples,
            )
        journal_ids = dict(
            session.execute(
                select(Journal.code, Journal.id).where(Journal.tenant_id == company_id)
            ).all()
        )
        numbers = {line.account for group in groups.values() for line in group.lines}
        account_ids = dict(
            session.execute(
                select(Account.number, Account.id).where(
                    Account.tenant_id == company_id, Account.number.in_(numbers)
                )
            ).all()
        )
        now = utcnow()
        created = 0
        total_lines = 0
        for group in groups.values():
            data = EntryData(
                journal_id=journal_ids[group.journal],
                entry_date=group.day,
                label=group.label,
                reference=group.source,
                lines=[
                    LineData(
                        account_id=account_ids[line.account],
                        debit=line.debit,
                        credit=line.credit,
                        label=line.label,
                    )
                    for line in group.lines
                ],
            )
            entry, _created = create_draft(session, actor, data, commit=False)
            session.add(
                ImportBatchEntry(batch_id=batch_id, tenant_id=company_id, entry_id=entry.id)
            )
            created += 1
            total_lines += len(group.lines)
        batch.confirmed_at = now
        batch.confirmed_by_user_id = actor.user_id
        batch.confirmed_entries = created
        record_event(
            session,
            action="import.confirmed",
            entity_type="accounting_import_batch",
            entity_id=batch_id,
            payload={
                "entrees": created,
                "lignes": total_lines,
                "debit": report.debit,
                "credit": report.credit,
            },
            actor_user_id=actor.user_id,
            ip_address=actor.ctx.ip_address,
        )
        return ImportConfirmation(
            batch_id=batch_id,
            confirmed_at=now,
            entries=created,
            lines=total_lines,
            debit=report.debit,
            credit=report.credit,
        )
