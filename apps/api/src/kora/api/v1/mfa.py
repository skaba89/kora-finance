"""Routes de double authentification (TOTP)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from kora.api.v1.auth import TokenResponse
from kora.api.v1.common import RequestBody
from kora.auth import mfa
from kora.auth.deps import Ctx, CurrentUser, DbSession
from kora.core.config import get_settings
from kora.core.errors import ErrorResponse
from kora.core.rate_limit import rate_limit

router = APIRouter(prefix="/auth/mfa", tags=["authentification"])

_limit = rate_limit("auth-mfa", lambda: get_settings().auth_rate_limit_per_minute)
RateLimited = [Depends(_limit)]
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}

Code = Annotated[str, Field(min_length=6, max_length=20)]


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg_data_uri: str


class CodeRequest(RequestBody):
    code: Code


class MfaVerifyRequest(RequestBody):
    mfa_token: Annotated[str, Field(min_length=1, max_length=2000)]
    code: Code


class ReauthRequest(RequestBody):
    password: Annotated[str, Field(min_length=1, max_length=256)]
    code: Code


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


@router.post("/setup", responses=_ERRORS)
def setup(user: CurrentUser, db: DbSession, ctx: Ctx) -> MfaSetupResponse:
    result = mfa.start_setup(db, user, ctx)
    return MfaSetupResponse(
        secret=result.secret, otpauth_uri=result.otpauth_uri, qr_svg_data_uri=result.qr_svg_data_uri
    )


@router.post("/enable", dependencies=RateLimited, responses=_ERRORS)
def enable(body: CodeRequest, user: CurrentUser, db: DbSession, ctx: Ctx) -> RecoveryCodesResponse:
    return RecoveryCodesResponse(recovery_codes=mfa.enable(db, user, body.code, ctx))


@router.post(
    "/verify", dependencies=RateLimited, responses={**_ERRORS, 423: {"model": ErrorResponse}}
)
def verify(body: MfaVerifyRequest, db: DbSession, ctx: Ctx) -> TokenResponse:
    return TokenResponse.of(
        mfa.complete_login(db, mfa_token=body.mfa_token, code=body.code, ctx=ctx)
    )


@router.post(
    "/disable", status_code=status.HTTP_204_NO_CONTENT, dependencies=RateLimited, responses=_ERRORS
)
def disable(body: ReauthRequest, user: CurrentUser, db: DbSession, ctx: Ctx) -> None:
    mfa.disable(db, user, password=body.password, code=body.code, ctx=ctx)


@router.post("/recovery-codes", dependencies=RateLimited, responses=_ERRORS)
def regenerate(
    body: ReauthRequest, user: CurrentUser, db: DbSession, ctx: Ctx
) -> RecoveryCodesResponse:
    codes = mfa.regenerate_recovery_codes(db, user, password=body.password, code=body.code, ctx=ctx)
    return RecoveryCodesResponse(recovery_codes=codes)
