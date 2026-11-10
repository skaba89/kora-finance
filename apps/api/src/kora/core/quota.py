"""Quotas à fenêtre fixe (Redis) : bornent le débit d'opérations coûteuses ou
abusibles — emails transactionnels, exports PDF/Excel (KF-13), invitations…

Une panne Redis lève une exception : la protection n'est jamais désactivée
silencieusement (mieux vaut refuser une opération que laisser un conteneur
saturer CPU et mémoire sans garde-fou).
"""

import logging
import time

from redis.exceptions import RedisError

from kora.core.redis import get_redis

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR


def allowed(scope: str, subject: str, *, limit: int, window_seconds: int) -> bool:
    """Compte une opération ; faux si `limit` est dépassée dans la fenêtre courante."""
    key = f"quota:{scope}:{subject}:{int(time.time()) // window_seconds}"
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds * 2)
        count = int(pipe.execute()[0])
    except RedisError:
        logger.exception("Quota indisponible (Redis)", extra={"scope": scope})
        raise
    return count <= limit


def retry_after(window_seconds: int) -> str:
    return str(window_seconds - int(time.time()) % window_seconds)
