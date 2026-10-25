"""Acteurs Dramatiq. Lancement : `dramatiq kora.worker.tasks`."""

import logging
import uuid
from collections.abc import Callable

import dramatiq
from sqlalchemy.orm import Session

from kora.auth import recovery
from kora.core.config import get_settings
from kora.core.logging import configure_logging
from kora.db.session import get_sessionmaker
from kora.email import sender
from kora.email.sender import OutgoingEmail
from kora.organization import invitations
from kora.storage import objects
from kora.worker import broker as _broker  # noqa: F401  (enregistre le broker)

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)

# Réessais espacés (de 10 s à 30 min) : une panne du fournisseur d'email n'est pas fatale.
_RETRIES = 8
_MIN_BACKOFF_MS = 10_000
_MAX_BACKOFF_MS = 30 * 60_000


@dramatiq.actor(max_retries=0)
def ping(token: str) -> str:
    """Tâche de diagnostic : prouve que la chaîne API → Redis → worker fonctionne."""
    logger.info("ping reçu", extra={"token": token})
    return token


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def deliver_email(message: dict[str, str]) -> None:
    email = OutgoingEmail(**message)
    sender.send(email)
    # Jamais le contenu : il contient des liens à usage unique.
    logger.info("email envoyé", extra={"sujet": email.subject})


def _prepare_and_deliver(prepare: Callable[[Session], OutgoingEmail | None]) -> None:
    """Prépare l'email (jeton en base) puis le confie à `deliver_email`, qui réessaie."""
    with get_sessionmaker()() as session:
        email = prepare(session)
    if email is not None:
        deliver_email.send(email.to_dict())


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def delete_stored_object(object_key: str) -> None:
    """Suppression différée d'un objet dont la référence a déjà quitté la base."""
    objects.delete(object_key)
    logger.info("objet supprimé du stockage", extra={"objet": object_key})


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def request_password_reset(email: str) -> None:
    _prepare_and_deliver(lambda s: recovery.prepare_password_reset(s, email))


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def send_email_verification(user_id: str) -> None:
    _prepare_and_deliver(lambda s: recovery.prepare_email_verification(s, uuid.UUID(user_id)))


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def notify_password_changed(user_id: str) -> None:
    _prepare_and_deliver(lambda s: recovery.prepare_password_changed_notice(s, uuid.UUID(user_id)))


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def send_invitation(invitation_id: str) -> None:
    _prepare_and_deliver(lambda s: invitations.prepare_email(s, uuid.UUID(invitation_id)))
