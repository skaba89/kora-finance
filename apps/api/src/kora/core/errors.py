"""Erreurs métier exposées à l'API, au format `{"detail": …, "code": …, "errors": […]}`.

`detail` est un message en français affichable tel quel à l'utilisateur ; `code` est
stable et sert au frontend (traductions, comportements).
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str
    errors: list[str] = []


class KoraError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "erreur"

    def __init__(
        self,
        detail: str,
        *,
        errors: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors or []
        self.headers = headers


class NotFoundError(KoraError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "introuvable"


class ConflictError(KoraError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflit"


class ForbiddenError(KoraError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "interdit"


class UnauthenticatedError(KoraError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "non_authentifie"


class BusinessRuleError(KoraError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "regle_metier"


class TooManyRequestsError(KoraError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "trop_de_demandes"


class ServiceUnavailableError(KoraError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_indisponible"


class InvalidLinkError(KoraError):
    """Lien reçu par email inconnu, expiré, déjà utilisé ou révoqué."""

    code = "lien_invalide"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(KoraError)
    def _handle(_: Request, exc: KoraError) -> JSONResponse:
        body = ErrorResponse(detail=exc.detail, code=exc.code, errors=exc.errors)
        return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)
