"""Exports PDF et Excel : balance, grand livre, journal des écritures, états financiers, TFT."""

import uuid
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from kora.accounting import reports
from kora.api.v1.common import TENANT_ERRORS
from kora.auth.deps import Ctx, DbSession
from kora.core.errors import ErrorResponse
from kora.exports import service
from kora.exports.service import Format, Kind
from kora.tenancy.deps import EntriesRead

router = APIRouter(prefix="/companies/{company_id}/exports", tags=["exports"])

_FILE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {
            media: {"schema": {"type": "string", "format": "binary"}}
            for media in service.MEDIA_TYPES.values()
        },
        "description": "Fichier exporté",
    },
    **TENANT_ERRORS,
    422: TENANT_ERRORS[404],
    # KF-13 : quota d'exports dépassé (par utilisateur ou par dossier).
    429: {"model": ErrorResponse},
}

FileFormat = Annotated[Format, Query(alias="format", description="pdf ou xlsx")]


def _export(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    *,
    kind: Kind,
    file_format: Format,
    fiscal_year_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
    account_id: uuid.UUID | None = None,
) -> Response:
    period = reports.resolve_period(db, tenant.company_id, fiscal_year_id, date_from, date_to)
    exported = service.generate(
        db,
        tenant.company_id,
        period,
        kind=kind,
        file_format=file_format,
        actor_user_id=tenant.user.id,
        ctx=ctx,
        account_id=account_id,
    )
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{exported.filename}"; '
                f"filename*=UTF-8''{quote(exported.filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/trial-balance", response_class=Response, responses=_FILE)
def export_trial_balance(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    fiscal_year_id: uuid.UUID,
    file_format: FileFormat,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    return _export(
        tenant, db, ctx, kind="balance", file_format=file_format,
        fiscal_year_id=fiscal_year_id, date_from=date_from, date_to=date_to,
    )  # fmt: skip


@router.get("/ledger", response_class=Response, responses=_FILE)
def export_ledger(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    fiscal_year_id: uuid.UUID,
    file_format: FileFormat,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: Annotated[uuid.UUID | None, Query(description="Un compte ; tous si absent")] = None,
) -> Response:
    return _export(
        tenant, db, ctx, kind="grand-livre", file_format=file_format,
        fiscal_year_id=fiscal_year_id, date_from=date_from, date_to=date_to, account_id=account_id,
    )  # fmt: skip


@router.get("/entries", response_class=Response, responses=_FILE)
def export_entries(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    fiscal_year_id: uuid.UUID,
    file_format: FileFormat,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    return _export(
        tenant, db, ctx, kind="ecritures", file_format=file_format,
        fiscal_year_id=fiscal_year_id, date_from=date_from, date_to=date_to,
    )  # fmt: skip


@router.get("/financial-statements", response_class=Response, responses=_FILE)
def export_financial_statements(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    fiscal_year_id: uuid.UUID,
    file_format: FileFormat,
    date_to: date | None = None,
) -> Response:
    return _export(
        tenant, db, ctx, kind="etats-financiers", file_format=file_format,
        fiscal_year_id=fiscal_year_id, date_from=None, date_to=date_to,
    )  # fmt: skip


@router.get("/cash-flow-statement", response_class=Response, responses=_FILE)
def export_cash_flow_statement(
    tenant: EntriesRead,
    db: DbSession,
    ctx: Ctx,
    fiscal_year_id: uuid.UUID,
    file_format: FileFormat,
    date_to: date | None = None,
) -> Response:
    """Export du tableau des flux de trésorerie (KF-15), même chemin que les états."""
    return _export(
        tenant, db, ctx, kind="tft", file_format=file_format,
        fiscal_year_id=fiscal_year_id, date_from=None, date_to=date_to,
    )  # fmt: skip
