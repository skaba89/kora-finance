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
from kora.db.tenant import bind_tenant
from kora.email import sender
from kora.email.sender import OutgoingEmail, SerializedEmail
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
def deliver_email(message: SerializedEmail) -> None:
    email = OutgoingEmail.from_dict(message)
    sender.send(email)
    # Jamais le contenu : il contient des liens à usage unique ou des données client.
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


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def send_sales_reminder(tenant_id: str, reminder_id: str) -> None:
    """Relance de facture échue (4D) : l'email est composé depuis l'état
    persisté puis confié à `deliver_email`. Le tenant est lié explicitement à
    la session : les tables de vente sont sous RLS forcée et une session sans
    tenant n'y voit aucune ligne (échec fermé)."""
    # Import local obligatoire : importer `kora.sales` au niveau du module créerait
    # un cycle (accounting.entries → attachments.service → worker.tasks → sales).
    from kora.sales import reminders  # noqa: PLC0415

    try:
        with get_sessionmaker()() as session:
            bind_tenant(session, uuid.UUID(tenant_id))
            email = reminders.prepare_email(session, uuid.UUID(reminder_id))
    except LookupError:
        # La relance a disparu (dossier supprimé) : aucun envoi, aucun réessai.
        logger.info("relance disparue, envoi abandonné", extra={"relance": reminder_id})
        return
    deliver_email.send(email.to_dict())


@dramatiq.actor(max_retries=_RETRIES, min_backoff=_MIN_BACKOFF_MS, max_backoff=_MAX_BACKOFF_MS)
def send_sales_document_email(tenant_id: str, document_email_id: str) -> None:
    """Envoi d'un document de vente par email avec son PDF en pièce jointe
    (4D-bis). Même discipline que la relance : l'email est composé depuis l'état
    persisté (tenant lié explicitement pour la RLS), le PDF est rendu depuis les
    instantanés figés à l'émission — jamais depuis les fiches vivantes."""
    # Import local obligatoire (même cycle que ci-dessus).
    from kora.sales import document_emails  # noqa: PLC0415

    try:
        with get_sessionmaker()() as session:
            bind_tenant(session, uuid.UUID(tenant_id))
            email = document_emails.prepare_email(session, uuid.UUID(document_email_id))
    except LookupError:
        # L'envoi a disparu (dossier supprimé) : aucun envoi, aucun réessai.
        logger.info("envoi disparu, abandon", extra={"envoi": document_email_id})
        return
    except ValueError as exc:
        # État devenu non envoyable entre la mise en file et le traitement
        # (facture annulée…) : abandon sans réessai — renvoyer serait trompeur.
        logger.info("envoi abandonné : %s", exc, extra={"envoi": document_email_id})
        return
    deliver_email.send(email.to_dict())


# --- Relances automatiques (Phase B, lot 2) ------------------------------------
# Le balayage et l'exécution sont idempotents (unicité quotidienne en base,
# même contrat que la relance 4D) : max_retries=0 — un échec transitoire attend
# le balayage suivant au lieu de multiplier les réessais.


@dramatiq.actor(max_retries=0)
def scan_automatic_reminders() -> None:
    """Balayage périodique : enfile une exécution de politique par dossier. La
    sélection des dossiers passe par `companies` (racine du tenant, hors RLS) ;
    chaque exécution lie explicitement son tenant — les tables de vente sont
    sous RLS forcée et une session sans tenant n'y voit aucune ligne (échec
    fermé). Un dossier sans politique active termine immédiatement."""
    from sqlalchemy import select  # noqa: PLC0415

    from kora.models.identity import Company  # noqa: PLC0415

    with get_sessionmaker()() as session:
        ids = list(session.execute(select(Company.id)).scalars())
    for company_id in ids:
        run_reminder_policy.send(str(company_id))
    logger.info("balayage des relances automatiques enfilé", extra={"dossiers": len(ids)})


@dramatiq.actor(max_retries=0)
def run_reminder_policy(tenant_id: str, as_of_iso: str | None = None) -> None:
    """Exécute la politique de relance automatique d'un dossier (lot 2) :
    crée les relances dues (règles 4D : facture émise, échue, non soldée ;
    une par facture et par jour) puis enfile l'envoi email de chacune. Un
    échec de file laisse la relance enregistrée (renvoi depuis l'historique)."""
    # Import local obligatoire (même cycle que send_sales_reminder).
    from datetime import date  # noqa: PLC0415

    from kora.models.common import utcnow  # noqa: PLC0415
    from kora.sales import auto_reminders  # noqa: PLC0415

    as_of = date.fromisoformat(as_of_iso) if as_of_iso else utcnow().date()
    with get_sessionmaker()() as session:
        bind_tenant(session, uuid.UUID(tenant_id))
        run = auto_reminders.run_policy(session, uuid.UUID(tenant_id), as_of)
    if not run.enabled:
        logger.info("politique de relance inactive", extra={"dossier": tenant_id})
        return
    for reminder_id in run.created:
        try:
            send_sales_reminder.send(tenant_id, str(reminder_id))
            run.emails_queued += 1
        except Exception:
            logger.exception("mise en file de l'email de relance impossible")
    logger.info(
        "politique de relance exécutée",
        extra={
            "dossier": tenant_id,
            "jour": as_of.isoformat(),
            "relances": len(run.created),
            "emails_en_file": run.emails_queued,
            "a_jour": run.a_jour,
            "sans_email": run.sans_email,
            "doublons": run.doublons,
        },
    )


@dramatiq.actor(max_retries=0)
def scan_import_maintenance() -> None:
    """Enfile la maintenance par dossier, sans accès aux imports hors RLS."""
    from sqlalchemy import select  # noqa: PLC0415

    from kora.models.identity import Company  # noqa: PLC0415

    with get_sessionmaker()() as session:
        ids = list(session.scalars(select(Company.id)))
    for company_id in ids:
        try:
            maintain_imports.send(str(company_id))
        except Exception:
            logger.exception("mise en file de la maintenance des imports impossible")


@dramatiq.actor(max_retries=0)
def maintain_imports(tenant_id: str) -> None:
    """Un lot borné de références expirées et le début du balayage S3."""
    from kora.accounting.import_purge import purge_expired_imports  # noqa: PLC0415

    removed = purge_expired_imports(uuid.UUID(tenant_id))
    logger.info("imports expirés purgés", extra={"dossier": tenant_id, "nombre": removed})
    reconcile_import_objects.send(tenant_id)


@dramatiq.actor(max_retries=0)
def reconcile_import_objects(tenant_id: str, cursor: str | None = None) -> None:
    """Une page S3 par message ; un échec sera repris au prochain balayage."""
    from kora.accounting.import_purge import purge_orphan_page  # noqa: PLC0415

    removed, next_cursor = purge_orphan_page(uuid.UUID(tenant_id), cursor=cursor)
    logger.info("imports orphelins purgés", extra={"dossier": tenant_id, "nombre": removed})
    if next_cursor is not None and next_cursor != cursor:
        reconcile_import_objects.send(tenant_id, next_cursor)
