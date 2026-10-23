"""Dépendances FastAPI d'authentification."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from kora.auth.service import RequestContext
from kora.auth.tokens import InvalidTokenError, decode_token
from kora.core.client_ip import client_ip
from kora.core.errors import UnauthenticatedError
from kora.db.session import get_db
from kora.models.identity import User

_bearer = HTTPBearer(auto_error=False, description="Jeton d'accès JWT")
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent")
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise UnauthenticatedError("Authentification requise.", headers=_CHALLENGE)
    try:
        claims = decode_token(credentials.credentials, "access")
    except InvalidTokenError as exc:
        raise UnauthenticatedError("Session invalide ou expirée.", headers=_CHALLENGE) from exc
    user = db.get(User, claims.user_id)
    # token_version : une déconnexion globale ou un changement de mot de passe
    # invalide immédiatement tous les jetons d'accès émis auparavant.
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise UnauthenticatedError("Session invalide ou expirée.", headers=_CHALLENGE)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
DbSession = Annotated[Session, Depends(get_db)]
