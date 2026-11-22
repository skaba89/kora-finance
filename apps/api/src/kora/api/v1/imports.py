"""Dépôt et précontrôle des imports comptables, sans création d'écriture."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from kora.accounting.import_service import precheck_staged_import
from kora.accounting.import_storage import stage_import
from kora.accounting.import_validation import ImportReport
from kora.api.v1.common import Money
from kora.core.errors import ErrorResponse, PayloadTooLargeError
from kora.tenancy.deps import EntriesWrite

router = APIRouter(prefix="/companies/{company_id}/accounting-imports", tags=["imports"])

# Sous le plafond de 12 MB du proxy, indépendamment des limites internes.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_REPORT_ISSUES = 200


class ImportBatchOut(BaseModel):
    id: uuid.UUID
    expires_at: datetime


class ImportIssueOut(BaseModel):
    row: int
    code: str


class ImportReportOut(BaseModel):
    rows: int
    entries: int
    debit: Money
    credit: Money
    valid: bool
    issue_count: int
    issues: list[ImportIssueOut]

    @classmethod
    def of(cls, report: ImportReport) -> "ImportReportOut":
        return cls(
            rows=report.rows,
            entries=report.entries,
            debit=report.debit,
            credit=report.credit,
            valid=report.valid,
            issue_count=len(report.issues),
            issues=[
                ImportIssueOut(row=issue.row, code=issue.code)
                for issue in report.issues[:MAX_REPORT_ISSUES]
            ],
        )


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError("Le fichier dépasse 10 Mio.")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError("Le fichier dépasse 10 Mio.")
        content.extend(chunk)
    return bytes(content)


_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 503)
}


@router.post(
    "",
    responses={**_ERRORS, 413: {"model": ErrorResponse}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "Fichier brut CSV, FEC ou XLSX (10 Mio maximum)",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_accounting_import(
    tenant: EntriesWrite,
    request: Request,
    file_format: Literal["csv", "fec", "xlsx"],
    source_currency: Annotated[str, Query(min_length=3, max_length=3)],
    fec_delimiter: Literal["\t", "|"] = "|",
) -> ImportBatchOut:
    content = await _read_body(request)
    result = await run_in_threadpool(
        stage_import,
        tenant.user,
        tenant.company_id,
        content,
        file_format=file_format,
        source_currency=source_currency,
        fec_delimiter=fec_delimiter,
    )
    return ImportBatchOut(id=result.id, expires_at=result.expires_at)


@router.post("/{batch_id}/precheck", responses=_ERRORS)
def precheck_accounting_import(tenant: EntriesWrite, batch_id: uuid.UUID) -> ImportReportOut:
    return ImportReportOut.of(precheck_staged_import(tenant.user, tenant.company_id, batch_id))
