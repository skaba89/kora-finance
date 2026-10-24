"""Quotas d'envoi d'emails (fenêtre fixe, Redis) : empêchent d'inonder une boîte ou
d'utiliser Kora pour envoyer du spam.

Une panne Redis lève une exception : la protection n'est jamais désactivée
silencieusement.
"""

import logging
import time

from redis.exceptions import RedisError

from kora.core.redis import get_redis

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR


def allowed(scope: str, subject: str, *, limit: int, window_seconds: int) -> bool:
    """Compte un envoi ; faux si `limit` est dépassée dans la fenêtre courante."""
    key = f"emails:{scope}:{subject}:{int(time.time()) // window_seconds}"
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds * 2)
        count = int(pipe.execute()[0])
    except RedisError:
        logger.exception("Quota d'emails indisponible (Redis)", extra={"scope": scope})
        raise
    return count <= limit


def retry_after(window_seconds: int) -> str:
    return str(window_seconds - int(time.time()) % window_seconds)
