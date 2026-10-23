"""Schémas communs aux routes : pagination, réponses d'erreur."""

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict

from kora.core.errors import ErrorResponse

MAX_PAGE_SIZE = 200

Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Taille de page")]
Offset = Annotated[int, Query(ge=0, description="Décalage")]


class RequestBody(BaseModel):
    """Base des corps de requête : tout champ inconnu est refusé (pas d'ignorance silencieuse)."""

    model_config = ConfigDict(extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


TENANT_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}
WRITE_ERRORS: dict[int | str, dict[str, object]] = {
    **TENANT_ERRORS,
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
