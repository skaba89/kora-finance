"""Configuration du broker Dramatiq.

Doit être importé avant toute déclaration d'acteur. En environnement de test, un
StubBroker en mémoire remplace Redis.
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from kora.core.config import Environment, get_settings


def _build_broker() -> dramatiq.Broker:
    settings = get_settings()
    if settings.env == Environment.TEST:
        return StubBroker()
    return RedisBroker(url=str(settings.redis_url))  # type: ignore[no-untyped-call]


broker = _build_broker()
dramatiq.set_broker(broker)
