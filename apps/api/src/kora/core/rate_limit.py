"""Limitation de débit par fenêtre fixe (Redis), appliquée par adresse IP.

Si Redis est indisponible, la requête est refusée (503) : on ne désactive pas
silencieusement une protection de sécurité.
"""

import logging
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from redis import Redis
from redis.exceptions import RedisError

from kora.core.client_ip import client_ip
from kora.core.redis import get_redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


def rate_limit(scope: str, limit_per_minute: Callable[[], int]) -> Callable[..., None]:
    """Dépendance FastAPI : au plus `limit_per_minute()` requêtes par minute et par IP."""

    def dependency(
        request: Request, response: Response, redis: Annotated[Redis, Depends(get_redis)]
    ) -> None:
        limit = limit_per_minute()
        window = int(time.time()) // WINDOW_SECONDS
        key = f"ratelimit:{scope}:{client_ip(request) or 'inconnu'}:{window}"
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS * 2)
            count = int(pipe.execute()[0])
        except RedisError as exc:
            logger.exception("Limitation de débit indisponible (Redis)", extra={"scope": scope})
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Service temporairement indisponible"
            ) from exc
        if count > limit:
            retry_after = WINDOW_SECONDS - int(time.time()) % WINDOW_SECONDS
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Trop de tentatives. Réessayez dans une minute.",
                headers={"Retry-After": str(retry_after)},
            )
        response.headers["X-RateLimit-Remaining"] = str(max(limit - count, 0))

    return dependency
