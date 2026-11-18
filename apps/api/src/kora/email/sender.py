"""Envoi des emails : SMTP générique (tout fournisseur) ou boîte en mémoire (tests).

L'envoi a lieu dans le worker (`kora.worker.tasks.deliver_email`), jamais pendant une
requête HTTP : une panne du fournisseur ne bloque pas l'utilisateur et l'envoi est
réessayé.
"""

import base64
import logging
import smtplib
import ssl
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import TypedDict

from kora.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingAttachment:
    """Pièce jointe d'un email (4D-bis : le PDF du document de vente).

    Le contenu voyage en base64 : la file Dramatiq sérialise les messages en
    JSON, qui ne porte pas d'octets bruts. Le décodage a lieu à la composition
    MIME, dans le worker uniquement."""

    filename: str
    content_b64: str
    mime_type: str = "application/pdf"

    @classmethod
    def from_bytes(
        cls, filename: str, content: bytes, mime_type: str = "application/pdf"
    ) -> "OutgoingAttachment":
        return cls(
            filename=filename,
            content_b64=base64.b64encode(content).decode("ascii"),
            mime_type=mime_type,
        )

    def content(self) -> bytes:
        return base64.b64decode(self.content_b64)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    attachments: tuple[OutgoingAttachment, ...] = ()

    def to_dict(self) -> "SerializedEmail":
        return asdict(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, message: "SerializedEmail") -> "OutgoingEmail":
        """Réhydratation d'un message sorti de la file (JSON) : les pièces
        jointes reviennent en dictionnaires et reprennent leur forme dataclass."""
        attachments = tuple(
            a if isinstance(a, OutgoingAttachment) else OutgoingAttachment(**a)
            for a in message.get("attachments", [])
        )
        return cls(
            to=message["to"],
            subject=message["subject"],
            text=message["text"],
            html=message["html"],
            attachments=attachments,
        )


class SerializedEmail(TypedDict, total=False):
    """Forme sérialisée d'un email dans la file Dramatiq (JSON) : les champs
    obligatoires d'un message complet sont présents à l'envoi ; `attachments`
    est absent d'un message composé avant l'introduction des pièces jointes."""

    to: str
    subject: str
    text: str
    html: str
    attachments: list[dict[str, str]]


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
    for attachment in message.attachments:
        maintype, _, subtype = attachment.mime_type.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        mime.add_attachment(
            attachment.content(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
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
