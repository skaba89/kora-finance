"""Routes publiques des invitations : consultation et acceptation par l'invité."""

import uuid
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from kora.api.v1.auth import RATE_LIMITED, TokenResponse
from kora.api.v1.common import RequestBody
from kora.auth import service as auth_service
from kora.auth.deps import Ctx, CurrentUser, DbSession
from kora.core.errors import ErrorResponse
from kora.organization import invitations
from kora.tenancy.roles import Role

router = APIRouter(prefix="/invitations", tags=["invitations"])

Token = Annotated[str, Field(min_length=1, max_length=200)]
_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


class InvitationTokenRequest(RequestBody):
    token: Token


class AcceptInvitationRequest(RequestBody):
    token: Token
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class InvitationPreviewOut(BaseModel):
    email: str
    company_name: str
    role: Role
    inviter_name: str
    account_exists: bool


class InvitationAcceptedResponse(TokenResponse):
    company_id: uuid.UUID


class JoinedCompany(BaseModel):
    company_id: uuid.UUID


@router.post("/preview", dependencies=RATE_LIMITED, responses=_ERRORS)
def preview(body: InvitationTokenRequest, db: DbSession) -> InvitationPreviewOut:
    found = invitations.preview(db, body.token)
    return InvitationPreviewOut(
        email=found.email,
        company_name=found.company_name,
        role=Role(found.role),
        inviter_name=found.inviter_name,
        account_exists=found.account_exists,
    )


@router.post(
    "/accept",
    status_code=status.HTTP_201_CREATED,
    dependencies=RATE_LIMITED,
    responses={**_ERRORS, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def accept(body: AcceptInvitationRequest, db: DbSession, ctx: Ctx) -> InvitationAcceptedResponse:
    """Crée le compte de l'invité, le rattache au dossier et ouvre sa session."""
    user, company_id = invitations.accept_with_new_account(
        db, token=body.token, full_name=body.full_name, password=body.password, ctx=ctx
    )
    pair = auth_service.open_session(db, user, ctx)
    db.commit()
    return InvitationAcceptedResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
        company_id=company_id,
    )


@router.post(
    "/join",
    dependencies=RATE_LIMITED,
    responses={**_ERRORS, 401: {"model": ErrorResponse}},
)
def join(body: InvitationTokenRequest, user: CurrentUser, db: DbSession, ctx: Ctx) -> JoinedCompany:
    """Acceptation par un utilisateur déjà connecté (adresse identique à l'invitation)."""
    return JoinedCompany(company_id=invitations.accept_as(db, user, token=body.token, ctx=ctx))
