"""Acteurs Dramatiq. Lancement : `dramatiq kora.worker.tasks`."""

import logging

import dramatiq

from kora.core.config import get_settings
from kora.core.logging import configure_logging
from kora.worker import broker as _broker  # noqa: F401  (enregistre le broker)

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


@dramatiq.actor(max_retries=0)
def ping(token: str) -> str:
    """Tâche de diagnostic : prouve que la chaîne API → Redis → worker fonctionne."""
    logger.info("ping reçu", extra={"token": token})
    return token
