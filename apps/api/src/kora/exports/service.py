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
from kora.core.errors import BusinessRuleError, NotFoundError
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
    document: Document
    if kind == "balance":
        document = builders.trial_balance(session, company, period)
    elif kind == "grand-livre":
        document = builders.ledger(session, company, period, account_id)
    elif kind == "ecritures":
        document = builders.entries(session, company, period)
    else:
        document = builders.financial_statements(session, company, period)

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
