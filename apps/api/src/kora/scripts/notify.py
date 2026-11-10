"""Notification d'exploitation par email (KF-12) : échec de sauvegarde, sonde externe.

Usage : `python -m kora.scripts.notify <sujet> <corps>`

Destinataire : KORA_ALERT_EMAIL — une adresse d'exploitation, distincte des emails
transactionnels des utilisateurs. Sans destinataire, ou avec KORA_EMAIL_BACKEND=
disabled, l'alerte n'est pas envoyée : le script l'affiche et sort en échec pour que
l'incident reste visible dans le journal systemd. Aucun secret n'est transmis : le
texte est rédigé par l'appelant (alert.sh).
"""

import html
import sys

from kora.core.config import get_settings
from kora.email import sender


def notify(subject: str, body: str) -> bool:
    """Envoie l'alerte si l'exploitation est configurée ; retourne True si envoyée."""
    settings = get_settings()
    if not settings.alert_email:
        print("KORA_ALERT_EMAIL n'est pas configuré : alerte journalisée uniquement.")
        return False
    if settings.email_backend == "disabled":
        print("KORA_EMAIL_BACKEND=disabled : alerte journalisée uniquement.")
        return False
    sender.send(
        sender.OutgoingEmail(
            to=settings.alert_email,
            subject=subject,
            text=body,
            html=f"<p>{html.escape(body).replace('\n', '<br>')}</p>",
        )
    )
    return True


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or not argv[0] or not argv[1]:
        raise SystemExit("Usage : python -m kora.scripts.notify <sujet> <corps>")
    sent = notify(argv[0], argv[1])
    print("Alerte envoyée." if sent else "Alerte non envoyée (voir ci-dessus).")
    sys.exit(0 if sent else 1)


if __name__ == "__main__":
    main()
