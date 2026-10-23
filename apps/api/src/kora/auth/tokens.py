"""Jetons JWT signés (HS256) : accès et défi MFA. Les refresh tokens sont opaques
(voir `refresh.py`)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import jwt

from kora.core.config import get_settings
from kora.models.common import utcnow

TokenType = Literal["access", "mfa"]
ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_version: int
    jti: str


def _encode(user_id: uuid.UUID, token_version: int, typ: TokenType, ttl: int) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "tv": token_version,
        "typ": typ,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID, token_version: int) -> str:
    return _encode(user_id, token_version, "access", get_settings().access_token_ttl_seconds)


def create_mfa_token(user_id: uuid.UUID, token_version: int) -> str:
    return _encode(user_id, token_version, "mfa", get_settings().mfa_challenge_ttl_seconds)


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "nbf", "sub", "jti", "aud", "iss"]},
            leeway=10,
        )
        if claims.get("typ") != expected_type:
            raise InvalidTokenError("type de jeton inattendu")
        return TokenClaims(
            user_id=uuid.UUID(claims["sub"]), token_version=int(claims["tv"]), jti=claims["jti"]
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
