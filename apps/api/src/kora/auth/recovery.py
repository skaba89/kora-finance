"""Réinitialisation du mot de passe et vérification de l'adresse email.

Les fonctions `prepare_*` tournent dans le worker : elles créent le jeton et renvoient
l'email à expédier. La demande de réinitialisation ne révèle jamais, ni par sa réponse
ni par son temps de réponse, si un compte existe : l'API se contente de mettre la
demande en file d'attente.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kora.auth import refresh as refresh_tokens
from kora.auth.one_time import new_token, token_hash
from kora.auth.passwords import hash_password
from kora.auth.service import (
    RequestContext,
    audit_auth_event,
    check_password_policy,
    get_user_by_email,
)
from kora.core import quota
from kora.core.config import get_settings
from kora.core.errors import BusinessRuleError, InvalidLinkError, TooManyRequestsError
from kora.email import templates
from kora.email.sender import OutgoingEmail
from kora.models.common import utcnow
from kora.models.identity import EmailToken, EmailTokenPurpose, User

logger = logging.getLogger(__name__)


def account_email_allowed(user_id: uuid.UUID, kind: str) -> bool:
    """Au plus `account_emails_per_hour` emails d'un type donné par compte et par heure."""
    return quota.allowed(
        kind, str(user_id), limit=get_settings().account_emails_per_hour, window_seconds=quota.HOUR
    )


def _link(user: User, page: str, token: str) -> str:
    return f"{get_settings().web_public_url}/{user.locale}/{page}?jeton={token}"


def _issue(session: Session, user: User, purpose: EmailTokenPurpose, ttl: timedelta) -> str:
    now = utcnow()
    # Un seul lien valable à la fois : les précédents du même type sont neutralisés.
    session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token, digest = new_token()
    session.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            email=user.email,
            token_hash=digest,
            expires_at=now + ttl,
        )
    )
    return token


def _consume(session: Session, token: str, purpose: EmailTokenPurpose) -> EmailToken:
    record = session.execute(
        select(EmailToken)
        .where(EmailToken.token_hash == token_hash(token), EmailToken.purpose == purpose)
        .with_for_update()
    ).scalar_one_or_none()
    if record is None or record.used_at is not None or record.expires_at <= utcnow():
        raise InvalidLinkError("Ce lien est invalide ou a expiré. Faites une nouvelle demande.")
    record.used_at = utcnow()
    return record


# --- Mot de passe oublié


def prepare_password_reset(session: Session, email: str) -> OutgoingEmail | None:
    settings = get_settings()
    user = get_user_by_email(session, email)
    if user is None or not user.is_active:
        logger.info("Réinitialisation demandée pour une adresse sans compte actif")
        return None
    if not account_email_allowed(user.id, "password_reset"):
        logger.warning(
            "Réinitialisation : limite d'envoi atteinte", extra={"user_id": str(user.id)}
        )
        audit_auth_event(session, "auth.password_reset_throttled", user.id, RequestContext())
        session.commit()
        return None
    ttl = settings.password_reset_ttl_minutes
    token = _issue(session, user, EmailTokenPurpose.PASSWORD_RESET, timedelta(minutes=ttl))
    audit_auth_event(session, "auth.password_reset_requested", user.id, RequestContext())
    session.commit()
    return templates.render(
        "password_reset",
        user.locale,
        to=user.email,
        url=_link(user, "reinitialisation-mot-de-passe", token),
        name=user.full_name,
        ttl=ttl,
    )


def reset_password(session: Session, *, token: str, new_password: str, ctx: RequestContext) -> User:
    record = _consume(session, token, EmailTokenPurpose.PASSWORD_RESET)
    user = session.get(User, record.user_id, with_for_update=True)
    if user is None or not user.is_active or user.email != record.email:
        session.rollback()
        raise InvalidLinkError("Ce lien est invalide ou a expiré. Faites une nouvelle demande.")
    try:
        check_password_policy(new_password, user.email)
    except BusinessRuleError:
        # Le lien n'est pas consommé par une saisie refusée : l'utilisateur corrige.
        session.rollback()
        raise
    user.password_hash = hash_password(new_password)
    # Recevoir le lien prouve la maîtrise de l'adresse : elle est vérifiée de fait, et le
    # verrouillage pour échecs répétés est levé. La 2FA, elle, reste exigée.
    user.email_verified_at = user.email_verified_at or utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    user.token_version += 1
    refresh_tokens.revoke_all(session, user.id)
    audit_auth_event(session, "auth.password_reset", user.id, ctx)
    session.commit()
    return user


def prepare_password_changed_notice(session: Session, user_id: uuid.UUID) -> OutgoingEmail | None:
    user = session.get(User, user_id)
    if user is None:
        return None
    return templates.render("password_changed", user.locale, to=user.email, name=user.full_name)


# --- Vérification de l'adresse


def prepare_email_verification(session: Session, user_id: uuid.UUID) -> OutgoingEmail | None:
    user = session.get(User, user_id)
    if user is None or not user.is_active or user.email_verified_at is not None:
        return None
    ttl = get_settings().email_verification_ttl_hours
    token = _issue(session, user, EmailTokenPurpose.EMAIL_VERIFICATION, timedelta(hours=ttl))
    session.commit()
    return templates.render(
        "email_verification",
        user.locale,
        to=user.email,
        url=_link(user, "verification-email", token),
        name=user.full_name,
        ttl=ttl,
    )


def check_verification_resend(user: User) -> bool:
    """Vrai si un nouvel email doit partir ; lève 429 au-delà de la limite horaire."""
    if user.email_verified_at is not None:
        return False
    if not account_email_allowed(user.id, "email_verification"):
        raise TooManyRequestsError(
            "Trop d'emails envoyés à cette adresse. Réessayez dans une heure.",
            headers={"Retry-After": quota.retry_after(quota.HOUR)},
        )
    return True


def verify_email(session: Session, *, token: str, ctx: RequestContext) -> User:
    digest = token_hash(token)
    record = session.execute(
        select(EmailToken).where(
            EmailToken.token_hash == digest,
            EmailToken.purpose == EmailTokenPurpose.EMAIL_VERIFICATION,
        )
    ).scalar_one_or_none()
    if record is not None and record.used_at is not None:
        # Lien déjà utilisé alors que l'adresse est confirmée (double clic) : succès.
        user = session.get(User, record.user_id)
        if user is not None and user.email_verified_at is not None and user.email == record.email:
            return user
    record = _consume(session, token, EmailTokenPurpose.EMAIL_VERIFICATION)
    user = session.get(User, record.user_id, with_for_update=True)
    if user is None or user.email != record.email:
        session.rollback()
        raise InvalidLinkError("Ce lien est invalide ou a expiré. Faites une nouvelle demande.")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        audit_auth_event(session, "auth.email_verified", user.id, ctx)
    session.commit()
    return user
