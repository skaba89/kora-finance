"""Schémas communs aux routes : pagination, réponses d'erreur."""

import re
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, WithJsonSchema

from kora.core.errors import ErrorResponse

MAX_PAGE_SIZE = 200

Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Taille de page")]
Offset = Annotated[int, Query(ge=0, description="Décalage")]


_DIGITS = re.compile(r"0|[1-9][0-9]{0,17}")


def _parse_money(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and _DIGITS.fullmatch(value):
        return int(value)
    raise ValueError(
        'Montant attendu : entier positif en unités mineures, en chaîne (ex. "150000").'
    )


# Montant en unités mineures (GNF : 0 décimale). Transmis en chaîne de chiffres dans les
# deux sens : JavaScript ne représente exactement les entiers que jusqu'à 2^53, et
# aucune conversion en nombre flottant ne doit pouvoir altérer un montant.
Money = Annotated[
    int,
    BeforeValidator(_parse_money),
    PlainSerializer(str, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": "^(0|[1-9][0-9]*)$",
            "description": "Montant entier en unités mineures, sous forme de chaîne",
        }
    ),
]


# Solde signé (positif = débiteur, négatif = créditeur), en chaîne. Sortie uniquement.
SignedMoney = Annotated[
    int,
    PlainSerializer(str, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": "^-?(0|[1-9][0-9]*)$",
            "description": "Solde signé en unités mineures (positif = débiteur), en chaîne",
        }
    ),
]


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
