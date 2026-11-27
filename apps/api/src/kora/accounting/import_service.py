"""Précontrôle d'import dans un dossier autorisé, sans écriture comptable."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kora.accounting.import_business import ImportCatalog, ImportPeriod, validate_import
from kora.accounting.import_storage import load_staged_content
from kora.accounting.import_validation import ImportIssue, ImportReport
from kora.core.errors import ForbiddenError, NotFoundError
from kora.db.session import get_sessionmaker
from kora.db.snapshot import lecture_instantanee
from kora.db.tenant import bind_tenant
from kora.models.accounting import Account
from kora.models.common import utcnow
from kora.models.identity import Company, User
from kora.models.imports import ImportBatch, ImportBatchIssue
from kora.models.ledger import Journal
from kora.models.organization import FiscalYear, FiscalYearStatus
from kora.tenancy.access import resolve_role
from kora.tenancy.permissions import Permission, permissions_for

# Volumétrie bornée : au-delà, `issue_count` reste exact mais les lignes ne sont
# plus toutes conservées (le rapport HTTP complet reste disponible immédiatement
# après le précontrôle ; la revue paginée couvre le reste conservé).
MAX_PERSISTED_ISSUES = 1000


def _catalog(session: Session, company_id: uuid.UUID) -> ImportCatalog:
    journals = session.execute(
        select(Journal.code, Journal.is_active).where(Journal.tenant_id == company_id)
    ).all()
    accounts = session.execute(
        select(Account.number, Account.is_active).where(Account.tenant_id == company_id)
    ).all()
    years = session.execute(select(FiscalYear).where(FiscalYear.tenant_id == company_id)).scalars()
    return ImportCatalog(
        journals={code: active for code, active in journals},
        accounts={number: active for number, active in accounts},
        periods=[
            ImportPeriod(
                year.start_date,
                year.end_date,
                year.status == FiscalYearStatus.OPEN,
                year.locked_until,
            )
            for year in years
        ],
    )


def precheck_import_for_company(
    user: User,
    company_id: uuid.UUID,
    content: bytes,
    *,
    file_format: Literal["csv", "fec", "xlsx"],
    source_currency: str,
    fec_delimiter: Literal["\t", "|"] = "|",
) -> ImportReport:
    """Autorisation et catalogue sous un même instantané RLS.

    L'utilisateur doit provenir de l'authentification serveur. Le fichier est
    contrôlé après fermeture de la transaction : pas de connexion immobilisée
    pendant le parsing. Les droits et références devront être revérifiés lors
    de l'intégration effective. Le premier profil tenant accepte uniquement GNF.
    """
    with lecture_instantanee(company_id) as session:
        role = resolve_role(session, user, company_id)
        if role is None:
            raise NotFoundError("Dossier introuvable.")
        if Permission.ENTRIES_WRITE not in permissions_for(role):
            raise ForbiddenError("Votre rôle ne permet pas cette action.")
        currency = session.execute(
            select(Company.currency).where(Company.id == company_id)
        ).scalar_one_or_none()
        if currency is None:
            raise NotFoundError("Dossier introuvable.")
        if currency != source_currency:
            return ImportReport(issues=[ImportIssue(1, "currency_mismatch")])
        if currency != "GNF":
            return ImportReport(issues=[ImportIssue(1, "unsupported_currency")])
        catalog = _catalog(session, company_id)
    return validate_import(
        content, file_format=file_format, catalog=catalog, fec_scale=0, fec_delimiter=fec_delimiter
    )


def precheck_staged_import(user: User, company_id: uuid.UUID, batch_id: uuid.UUID) -> ImportReport:
    """Précontrôle d'un fichier chiffré avec ses options persistées, non modifiables.

    Les droits sont revérifiés lors du chargement puis du contrôle du catalogue.
    Aucun contenu source ni écriture comptable n'est renvoyé ou créé.
    """
    staged = load_staged_content(user, company_id, batch_id)
    return precheck_import_for_company(
        user,
        company_id,
        staged.content,
        file_format=staged.file_format,
        source_currency=staged.currency,
        fec_delimiter=staged.fec_delimiter,
    )


@dataclass(frozen=True)
class PersistedPrecheck:
    """Rapport persisté : synthèse complète et page d'anomalies demandée."""

    precheck_at: datetime
    rows: int
    entries: int
    debit: int
    credit: int
    valid: bool
    issue_count: int
    stored_issues: int
    issues: list[ImportIssue] = field(default_factory=list)


def precheck_and_persist(user: User, company_id: uuid.UUID, batch_id: uuid.UUID) -> ImportReport:
    """Précontrôle puis remplace le rapport conservé du batch (synthèse + anomalies).

    Deux précontrôles concurrents se sérialisent sur le verrou de ligne du batch :
    l'état final est idempotent (dernier rapport gagnant, aucune ligne dupliquée).
    """
    report = precheck_staged_import(user, company_id, batch_id)
    issues = report.issues[:MAX_PERSISTED_ISSUES]
    with get_sessionmaker()() as session, session.begin():
        bind_tenant(session, company_id)
        batch = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == company_id, ImportBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None or batch.expires_at <= utcnow():
            raise NotFoundError("Import introuvable ou expiré.")
        batch.precheck_at = utcnow()
        batch.precheck_rows = report.rows
        batch.precheck_entries = report.entries
        batch.precheck_debit = report.debit
        batch.precheck_credit = report.credit
        batch.precheck_valid = report.valid
        batch.precheck_issue_count = len(report.issues)
        batch.precheck_stored_issues = len(issues)
        session.execute(delete(ImportBatchIssue).where(ImportBatchIssue.batch_id == batch_id))
        session.add_all(
            ImportBatchIssue(
                batch_id=batch_id,
                tenant_id=company_id,
                seq=seq,
                row_number=issue.row,
                code=issue.code,
            )
            for seq, issue in enumerate(issues)
        )
    return report


def _authorize_report_read(session: Session, user: User, company_id: uuid.UUID) -> None:
    bind_tenant(session, company_id)
    role = resolve_role(session, user, company_id)
    if role is None:
        raise NotFoundError("Dossier introuvable.")
    if Permission.ENTRIES_WRITE not in permissions_for(role):
        raise ForbiddenError("Votre rôle ne permet pas cette action.")


def read_precheck_report(
    user: User,
    company_id: uuid.UUID,
    batch_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> PersistedPrecheck:
    """Relecture autorisée du rapport conservé, anomalies par pages ordonnées.

    Chaque lecture repasse par l'autorisation et la RLS ; un batch expiré ou
    sans rapport persisté est introuvable. `limit` et `offset` portent sur les
    anomalies conservées (jamais sur le contenu du fichier, jamais rechargé).
    """
    with get_sessionmaker()() as session, session.begin():
        _authorize_report_read(session, user, company_id)
        batch = session.scalar(
            select(ImportBatch).where(
                ImportBatch.tenant_id == company_id,
                ImportBatch.id == batch_id,
                ImportBatch.expires_at > utcnow(),
            )
        )
        if batch is None or batch.precheck_at is None:
            raise NotFoundError("Rapport de précontrôle indisponible.")
        page = session.execute(
            select(ImportBatchIssue.row_number, ImportBatchIssue.code)
            .where(ImportBatchIssue.batch_id == batch_id)
            .order_by(ImportBatchIssue.seq)
            .offset(offset)
            .limit(limit)
        ).all()
        return PersistedPrecheck(
            precheck_at=batch.precheck_at,
            rows=int(batch.precheck_rows or 0),
            entries=int(batch.precheck_entries or 0),
            debit=int(batch.precheck_debit or 0),
            credit=int(batch.precheck_credit or 0),
            valid=bool(batch.precheck_valid),
            issue_count=int(batch.precheck_issue_count or 0),
            stored_issues=int(batch.precheck_stored_issues or 0),
            issues=[ImportIssue(row_number, code) for row_number, code in page],
        )
