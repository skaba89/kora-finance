"""Mise en file d'attente depuis l'API."""

import logging
from typing import Any

import dramatiq
from dramatiq.errors import BrokerConnectionError
from redis.exceptions import RedisError

from kora.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)


def enqueue(actor: dramatiq.Actor[..., Any], *args: str) -> None:
    """Envoie la tâche au worker ; 503 si la file d'attente est injoignable."""
    try:
        actor.send(*args)
    except (RedisError, BrokerConnectionError) as exc:
        logger.exception("File d'attente injoignable", extra={"tache": actor.actor_name})
        raise ServiceUnavailableError(
            "Service temporairement indisponible. Réessayez dans quelques instants."
        ) from exc


def enqueue_best_effort(actor: dramatiq.Actor[..., Any], *args: str) -> bool:
    """Pour un email secondaire après une action déjà validée (notification, premier
    email de vérification) : l'échec est journalisé, l'action n'est pas annulée, et
    l'utilisateur peut redemander l'email. Renvoie False en cas d'échec."""
    try:
        enqueue(actor, *args)
    except ServiceUnavailableError:
        return False
    return True
