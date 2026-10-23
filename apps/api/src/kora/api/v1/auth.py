"""Routes d'authentification : inscription, connexion, rafraîchissement, déconnexion."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field

from kora.auth import service
from kora.auth.deps import Ctx, CurrentUser, DbSession
from kora.core.config import get_settings
from kora.core.errors import ErrorResponse
from kora.core.rate_limit import rate_limit
from kora.models.identity import User

router = APIRouter(prefix="/auth", tags=["authentification"])

_auth_limit = rate_limit("auth", lambda: get_settings().auth_rate_limit_per_minute)
RateLimited = [Depends(_auth_limit)]

_ERRORS: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    locale: Literal["fr", "en"] = "fr"


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=200)]


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=1, max_length=256)]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    locale: str
    is_platform_admin: bool
    mfa_enabled: bool

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            locale=user.locale,
            is_platform_admin=user.is_platform_admin,
            mfa_enabled=user.totp_enabled_at is not None,
        )


class TokenResponse(BaseModel):
    status: Literal["authenticated"] = "authenticated"
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (type de jeton OAuth2, pas un secret)
    expires_in: int

    @classmethod
    def of(cls, pair: service.TokenPair) -> "TokenResponse":
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )


class MfaRequiredResponse(BaseModel):
    status: Literal["mfa_required"] = "mfa_required"
    mfa_token: str
    expires_in: int


LoginResponse = Annotated[TokenResponse | MfaRequiredResponse, Field(discriminator="status")]


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=RateLimited,
    responses={**_ERRORS, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def register(body: RegisterRequest, db: DbSession, ctx: Ctx) -> UserOut:
    user = service.register(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        locale=body.locale,
        ctx=ctx,
    )
    return UserOut.of(user)


@router.post(
    "/login", dependencies=RateLimited, responses={**_ERRORS, 423: {"model": ErrorResponse}}
)
def login(body: LoginRequest, db: DbSession, ctx: Ctx) -> LoginResponse:
    result = service.login(db, email=body.email, password=body.password, ctx=ctx)
    if isinstance(result, service.MfaChallenge):
        return MfaRequiredResponse(mfa_token=result.mfa_token, expires_in=result.expires_in)
    return TokenResponse.of(result)


@router.post("/refresh", dependencies=RateLimited, responses=_ERRORS)
def refresh(body: RefreshRequest, db: DbSession, ctx: Ctx) -> TokenResponse:
    return TokenResponse.of(service.refresh(db, token=body.refresh_token, ctx=ctx))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=RateLimited)
def logout(body: RefreshRequest, db: DbSession, ctx: Ctx) -> None:
    service.logout(db, token=body.refresh_token, ctx=ctx)


@router.post("/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
def logout_everywhere(user: CurrentUser, db: DbSession, ctx: Ctx) -> None:
    service.logout_everywhere(db, user, ctx)


@router.post(
    "/password", dependencies=RateLimited, responses={**_ERRORS, 422: {"model": ErrorResponse}}
)
def change_password(
    body: ChangePasswordRequest, user: CurrentUser, db: DbSession, ctx: Ctx
) -> TokenResponse:
    pair = service.change_password(
        db, user, current_password=body.current_password, new_password=body.new_password, ctx=ctx
    )
    return TokenResponse.of(pair)


@router.get("/me", responses=_ERRORS)
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
