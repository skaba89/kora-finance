"""Pièces justificatives des écritures : envoi, liste, téléchargement, retrait.

Le fichier est envoyé brut dans le corps de la requête (pas de multipart) ; le corps
est lu par morceaux et refusé dès qu'il dépasse la taille maximale.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from kora.accounting.entries import Actor
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS
from kora.attachments import service
from kora.auth.deps import Ctx, DbSession
from kora.core.config import get_settings
from kora.core.errors import ErrorResponse
from kora.models.attachments import Attachment, AttachmentType
from kora.tenancy.deps import EntriesRead, EntriesWrite, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["pièces justificatives"])


class AttachmentOut(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID
    filename: str
    content_type: AttachmentType
    size_bytes: int
    sha256: str
    created_at: datetime

    @classmethod
    def of(cls, attachment: Attachment) -> "AttachmentOut":
        return cls.model_validate(attachment, from_attributes=True)


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


async def _read_body(request: Request) -> bytes:
    limit = get_settings().attachment_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise service.too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise service.too_large()
        chunks.append(chunk)
    return b"".join(chunks)


_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": f"Contenu brut du fichier ({service.ACCEPTED_FORMATS})",
        "content": {
            media.value: {"schema": {"type": "string", "format": "binary"}}
            for media in AttachmentType
        },
    }
}


@router.post(
    "/entries/{entry_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_UPLOAD_BODY,
    responses={
        **WRITE_ERRORS,
        200: {"model": AttachmentOut, "description": "Fichier déjà attaché (réessai)"},
        413: {"model": ErrorResponse},
    },
)
async def add_attachment(
    tenant: EntriesWrite,
    db: DbSession,
    ctx: Ctx,
    entry_id: uuid.UUID,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    request: Request,
    response: Response,
) -> AttachmentOut:
    content = await _read_body(request)
    added = await run_in_threadpool(
        service.add, db, _actor(tenant, ctx), entry_id, filename, content
    )
    if not added.created:
        response.status_code = status.HTTP_200_OK
    return AttachmentOut.of(added.attachment)


@router.get("/entries/{entry_id}/attachments", responses=TENANT_ERRORS)
def list_attachments(
    tenant: EntriesRead, db: DbSession, entry_id: uuid.UUID
) -> list[AttachmentOut]:
    return [AttachmentOut.of(a) for a in service.list_for_entry(db, tenant.company_id, entry_id)]


_FILE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {
            media.value: {"schema": {"type": "string", "format": "binary"}}
            for media in AttachmentType
        },
        "description": "Contenu de la pièce",
    },
    **TENANT_ERRORS,
    409: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.get("/attachments/{attachment_id}/content", response_class=Response, responses=_FILE)
def attachment_content(
    tenant: EntriesRead,
    db: DbSession,
    attachment_id: uuid.UUID,
    disposition: Literal["inline", "attachment"] = "attachment",
) -> Response:
    attachment, content = service.read(db, tenant.company_id, attachment_id)
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f'{disposition}; filename="{quote(attachment.filename)}"; '
                f"filename*=UTF-8''{quote(attachment.filename)}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
def remove_attachment(
    tenant: EntriesWrite, db: DbSession, ctx: Ctx, attachment_id: uuid.UUID
) -> None:
    service.remove(db, _actor(tenant, ctx), attachment_id)
