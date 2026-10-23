"""Sondes de santé : `live` (processus vivant) et `ready` (dépendances joignables)."""

import logging
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["santé"])

CheckStatus = Literal["ok", "erreur"]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: CheckStatus
    database: CheckStatus
    redis: CheckStatus


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(str(get_settings().redis_url), socket_timeout=2)


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
def ready(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ReadyResponse:
    database: CheckStatus = "ok"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Sonde ready : base de données injoignable")
        database = "erreur"

    cache: CheckStatus = "ok"
    try:
        redis.ping()
    except RedisError:
        logger.exception("Sonde ready : Redis injoignable")
        cache = "erreur"

    overall: CheckStatus = "ok" if database == cache == "ok" else "erreur"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status=overall, database=database, redis=cache)
