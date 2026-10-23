"""Cas d'usage d'authentification. Chaque fonction gère sa transaction (commit)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth import refresh as refresh_tokens
from kora.auth.passwords import (
    hash_password,
    needs_rehash,
    password_policy_errors,
    verify_password,
)
from kora.auth.tokens import create_access_token, create_mfa_token
from kora.core.config import get_settings
from kora.core.errors import BusinessRuleError, ConflictError, KoraError, UnauthenticatedError
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import User

logger = logging.getLogger(__name__)


class InvalidCredentialsError(UnauthenticatedError):
    code = "identifiants_invalides"


class AccountLockedError(KoraError):
    status_code = 423
    code = "compte_verrouille"


class InvalidRefreshTokenError(UnauthenticatedError):
    code = "session_expiree"


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class MfaChallenge:
    mfa_token: str
    expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(
        select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()


def _audit(
    session: Session,
    action: str,
    user_id: uuid.UUID | None,
    ctx: RequestContext,
    payload: dict[str, str | int | bool | None] | None = None,
) -> None:
    # Événements d'authentification : chaîne plateforme (hors de tout dossier).
    bind_tenant(session, None)
    record_event(
        session,
        action=action,
        entity_type="user",
        entity_id=user_id,
        actor_user_id=user_id,
        payload=dict(payload or {}),
        ip_address=ctx.ip_address,
    )


def check_password_policy(password: str, email: str) -> None:
    errors = password_policy_errors(password, email=email)
    if errors:
        raise BusinessRuleError("Mot de passe non conforme.", errors=errors)


def register(
    session: Session, *, email: str, password: str, full_name: str, locale: str, ctx: RequestContext
) -> User:
    email = normalize_email(email)
    check_password_policy(password, email)
    if get_user_by_email(session, email) is not None:
        raise ConflictError("Un compte existe déjà avec cette adresse email.")
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        locale=locale,
    )
    session.add(user)
    session.flush()
    _audit(session, "user.registered", user.id, ctx)
    session.commit()
    return user


def open_session(session: Session, user: User, ctx: RequestContext) -> TokenPair:
    """Émet un jeton d'accès et ouvre une nouvelle famille de refresh tokens."""
    issued = refresh_tokens.issue(
        session, user, user_agent=ctx.user_agent, ip_address=ctx.ip_address
    )
    return TokenPair(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=issued.token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


def login(
    session: Session, *, email: str, password: str, ctx: RequestContext
) -> TokenPair | MfaChallenge:
    settings = get_settings()
    user = get_user_by_email(session, email)
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        # Pendant le verrouillage, le mot de passe n'est même pas vérifié (pas d'oracle).
        _audit(session, "auth.login_blocked", user.id, ctx)
        session.commit()
        raise AccountLockedError(
            "Compte temporairement verrouillé après plusieurs échecs. Réessayez plus tard.",
            headers={"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)},
        )

    valid = verify_password(user.password_hash if user else None, password)
    if user is None or not valid or not user.is_active:
        if user is not None:
            user.failed_login_count += 1
            locked = user.failed_login_count >= settings.login_max_failures
            _audit(
                session,
                "auth.login_failed",
                user.id,
                ctx,
                {"echecs_consecutifs": user.failed_login_count},
            )
            if locked:
                user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
                user.failed_login_count = 0
                _audit(
                    session,
                    "auth.account_locked",
                    user.id,
                    ctx,
                    {"duree_secondes": settings.login_lockout_seconds},
                )
            session.commit()
        else:
            logger.info(
                "Tentative de connexion sur un compte inconnu", extra={"ip": ctx.ip_address}
            )
        raise InvalidCredentialsError("Adresse email ou mot de passe incorrect.")

    user.failed_login_count = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    if user.totp_enabled_at is not None:
        _audit(session, "auth.mfa_challenge_issued", user.id, ctx)
        session.commit()
        return MfaChallenge(
            mfa_token=create_mfa_token(user.id, user.token_version),
            expires_in=settings.mfa_challenge_ttl_seconds,
        )

    pair = open_session(session, user, ctx)
    _audit(session, "auth.login_succeeded", user.id, ctx)
    session.commit()
    return pair


def refresh(session: Session, *, token: str, ctx: RequestContext) -> TokenPair:
    try:
        record = refresh_tokens.consume(session, token)
    except refresh_tokens.RefreshError as exc:
        if exc.reuse_detected:
            # La révocation de la famille doit être durable malgré l'erreur renvoyée.
            _audit(session, "auth.refresh_reuse_detected", exc.user_id, ctx)
            session.commit()
        else:
            session.rollback()
        raise InvalidRefreshTokenError("Session expirée. Veuillez vous reconnecter.") from exc

    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        session.rollback()
        raise InvalidRefreshTokenError("Session expirée. Veuillez vous reconnecter.")
    issued = refresh_tokens.issue(
        session,
        user,
        family_id=record.family_id,
        user_agent=ctx.user_agent,
        ip_address=ctx.ip_address,
    )
    session.commit()
    return TokenPair(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=issued.token,
        expires_in=get_settings().access_token_ttl_seconds,
    )


def logout(session: Session, *, token: str, ctx: RequestContext) -> None:
    """Ferme la session (famille) du refresh token. Idempotent."""
    record = refresh_tokens.find_family(session, token)
    if record is not None:
        refresh_tokens.revoke_family(session, record.family_id)
        _audit(session, "auth.logout", record.user_id, ctx)
    session.commit()


def logout_everywhere(session: Session, user: User, ctx: RequestContext) -> None:
    """Invalide tous les jetons d'accès et toutes les sessions de l'utilisateur."""
    user.token_version += 1
    refresh_tokens.revoke_all(session, user.id)
    _audit(session, "auth.logout_everywhere", user.id, ctx)
    session.commit()


def change_password(
    session: Session, user: User, *, current_password: str, new_password: str, ctx: RequestContext
) -> TokenPair:
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentialsError("Mot de passe actuel incorrect.")
    check_password_policy(new_password, user.email)
    user.password_hash = hash_password(new_password)
    # Toutes les autres sessions sont fermées ; l'appareil courant reçoit de nouveaux jetons.
    user.token_version += 1
    refresh_tokens.revoke_all(session, user.id)
    _audit(session, "auth.password_changed", user.id, ctx)
    pair = open_session(session, user, ctx)
    session.commit()
    return pair
