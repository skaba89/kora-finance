"""Envoi des emails : SMTP générique (tout fournisseur) ou boîte en mémoire (tests).

L'envoi a lieu dans le worker (`kora.worker.tasks.deliver_email`), jamais pendant une
requête HTTP : une panne du fournisseur ne bloque pas l'utilisateur et l'envoi est
réessayé.
"""

import logging
import smtplib
import ssl
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from kora.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# Boîte d'envoi du backend « memory » (KORA_ENV=test uniquement).
OUTBOX: list[OutgoingEmail] = []


def _mime(message: OutgoingEmail, settings: Settings) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = settings.email_from
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=parseaddr(settings.email_from)[1].rsplit("@", 1)[-1])
    # Emails transactionnels : pas de réponse automatique de type vacances.
    mime["Auto-Submitted"] = "auto-generated"
    mime.set_content(message.text)
    mime.add_alternative(message.html, subtype="html")
    return mime


def _send_smtp(mime: EmailMessage, settings: Settings) -> None:
    context = ssl.create_default_context()
    timeout = settings.smtp_timeout_seconds
    smtp: smtplib.SMTP
    if settings.smtp_security == "tls":
        smtp = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=timeout, context=context
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            password = settings.smtp_password.get_secret_value() if settings.smtp_password else ""
            smtp.login(settings.smtp_username, password)
        smtp.send_message(mime)


def send(message: OutgoingEmail) -> None:
    """Envoie immédiatement. Lève une exception en cas d'échec (le worker réessaie)."""
    settings = get_settings()
    if settings.email_backend == "memory":
        OUTBOX.append(message)
        return
    if settings.email_backend == "disabled":
        # Jamais le contenu ni le destinataire : liens à usage unique, données personnelles.
        logger.warning(
            "Email non envoyé : envoi désactivé (KORA_EMAIL_BACKEND=disabled)",
            extra={"sujet": message.subject},
        )
        return
    _send_smtp(_mime(message, settings), settings)
