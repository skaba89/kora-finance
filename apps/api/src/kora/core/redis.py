"""Client Redis partagé par le processus."""

from functools import lru_cache

from redis import Redis

from kora.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(str(get_settings().redis_url), socket_timeout=2)
