"""Génération des exports et traçabilité (chaque export est inscrit au journal d'audit)."""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from kora.accounting.reports import Period
from kora.audit.service import record_event
from kora.auth.service import RequestContext
from kora.core import quota
from kora.core.config import get_settings
from kora.core.errors import BusinessRuleError, NotFoundError, TooManyRequestsError
from kora.db.snapshot import lecture_instantanee
from kora.exports import builders, pdf, xlsx
from kora.exports.document import Document
from kora.models.identity import Company

Format = Literal["pdf", "xlsx"]
Kind = Literal["balance", "grand-livre", "ecritures", "etats-financiers"]

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
# Au-delà, un PDF devient illisible et coûteux à produire : Excel est proposé.
MAX_PDF_ROWS = 20_000


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    filename: str
    media_type: str


def _slug(text: str) -> str:
    # « Société Élégance » → « societe-elegance » : accents retirés, pas les lettres.
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower() or "dossier"


def generate(
    session: Session,
    company_id: uuid.UUID,
    period: Period,
    *,
    kind: Kind,
    file_format: Format,
    actor_user_id: uuid.UUID,
    ctx: RequestContext,
    account_id: uuid.UUID | None = None,
) -> ExportFile:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError("Dossier introuvable.")
    # KF-13 : budget d'exports. Chaque export est synchrone et coûteux (lecture
    # complète sous instantané, rendu PDF/Excel entièrement en mémoire) : sans quota,
    # quelques requêtes automatisées suffisent à saturer l'API. Deux compteurs : par
    # utilisateur (un compte ne peut pas tout consommer) et par dossier (l'ensemble
    # de ses membres reste borné). Comme pour les emails, une panne Redis interrompt
    # l'export (jamais de contournement silencieux).
    settings = get_settings()
    user_limit = settings.exports_per_user_per_hour
    user_allowed = quota.allowed(
        "export-user", str(actor_user_id), limit=user_limit, window_seconds=quota.HOUR
    )
    if not user_allowed:
        raise TooManyRequestsError(
            f"Limite de {user_limit} exports par heure atteinte pour votre compte.",
            headers={"Retry-After": quota.retry_after(quota.HOUR)},
        )
    company_limit = settings.exports_per_company_per_hour
    company_allowed = quota.allowed(
        "export-company", str(company_id), limit=company_limit, window_seconds=quota.HOUR
    )
    if not company_allowed:
        raise TooManyRequestsError(
            f"Limite de {company_limit} exports par heure atteinte pour ce dossier.",
            headers={"Retry-After": quota.retry_after(quota.HOUR)},
        )
    document: Document
    # KF-05 : les données du document sont lues sous un unique instantané (REPEATABLE
    # READ) — une validation concurrente ne peut pas mélanger deux instants dans un
    # même export (soldes des à-nouveaux sans leurs lignes, N et N-1 divergents…).
    with lecture_instantanee(company_id) as snap:
        if kind == "balance":
            document = builders.trial_balance(snap, company, period)
        elif kind == "grand-livre":
            document = builders.ledger(snap, company, period, account_id)
        elif kind == "ecritures":
            document = builders.entries(snap, company, period)
        else:
            document = builders.financial_statements(snap, company, period)

    rows = sum(len(section.rows) for section in document.sections)
    if file_format == "pdf" and rows > MAX_PDF_ROWS:
        raise BusinessRuleError(
            f"{rows} lignes : trop volumineux pour un PDF. "
            "Utilisez l'export Excel ou réduisez la période."
        )
    content = pdf.render(document) if file_format == "pdf" else xlsx.render(document)
    dates = f"{period.date_from:%Y%m%d}-{period.date_to:%Y%m%d}"
    filename = f"{kind}-{_slug(company.legal_name)}-{dates}.{file_format}"
    record_event(
        session,
        action="export.generated",
        entity_type="export",
        entity_id=None,
        payload={
            "type": kind,
            "format": file_format,
            "du": period.date_from.isoformat(),
            "au": period.date_to.isoformat(),
            "compte": str(account_id) if account_id else None,
            "lignes": rows,
        },
        actor_user_id=actor_user_id,
        ip_address=ctx.ip_address,
    )
    session.commit()
    return ExportFile(content, filename, MEDIA_TYPES[file_format])
