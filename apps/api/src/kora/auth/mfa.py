"""Double authentification TOTP (RFC 6238) et codes de secours."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

import pyotp
import segno
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kora.auth import refresh as refresh_tokens
from kora.auth.passwords import verify_password
from kora.auth.service import (
    AccountLockedError,
    InvalidCredentialsError,
    RequestContext,
    TokenPair,
    audit_auth_event,
    open_session,
)
from kora.auth.tokens import InvalidTokenError, decode_token
from kora.core.config import get_settings
from kora.core.crypto import decrypt, encrypt
from kora.core.errors import BusinessRuleError, ConflictError, UnauthenticatedError
from kora.models.common import utcnow
from kora.models.identity import RecoveryCode, User

ISSUER = "Kora Finance"
RECOVERY_CODE_COUNT = 10
# Alphabet sans caractères ambigus (0/O, 1/I/L) : 12 caractères ≈ 60 bits d'entropie.
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


class InvalidMfaCodeError(UnauthenticatedError):
    code = "code_mfa_invalide"


@dataclass(frozen=True)
class MfaSetup:
    secret: str
    otpauth_uri: str
    qr_svg_data_uri: str


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").upper().encode()).hexdigest()


def _new_recovery_codes(session: Session, user: User) -> list[str]:
    session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
        session.add(RecoveryCode(user_id=user.id, code_hash=_hash_recovery(raw)))
    return codes


def _match_totp_step(secret: str, code: str) -> int | None:
    """Renvoie le pas de temps correspondant au code (fenêtre ±1 pas), sinon None."""
    totp = pyotp.TOTP(secret)
    now = utcnow()
    current = totp.timecode(now)
    for offset in (0, -1, 1):
        candidate = totp.at(now + timedelta(seconds=offset * totp.interval))
        if hmac.compare_digest(candidate, code.strip()):
            return current + offset
    return None


def _verify_totp(user: User, code: str) -> bool:
    """Vérifie un code TOTP et empêche son rejeu (pas de temps déjà consommé)."""
    if user.totp_secret_encrypted is None:
        return False
    step = _match_totp_step(decrypt(user.totp_secret_encrypted), code)
    if step is None or (user.totp_last_used_step is not None and step <= user.totp_last_used_step):
        return False
    user.totp_last_used_step = step
    return True


def _consume_recovery_code(session: Session, user: User, code: str) -> bool:
    record = session.execute(
        select(RecoveryCode)
        .where(
            RecoveryCode.user_id == user.id,
            RecoveryCode.code_hash == _hash_recovery(code),
            RecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        return False
    record.used_at = utcnow()
    return True


def _locked_user(session: Session, user: User) -> User:
    """Recharge l'utilisateur sous verrou de ligne : les transitions du second facteur
    (enrôlement, activation, désactivation, régénération) sont sérialisées, à l'image
    de la connexion (KF-08)."""
    return session.execute(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _verify_current_password(user: User, password: str) -> None:
    if not verify_password(user.password_hash, password):
        raise InvalidCredentialsError("Mot de passe incorrect.")


def start_setup(session: Session, user: User, *, password: str, ctx: RequestContext) -> MfaSetup:
    user = _locked_user(session, user)
    _verify_current_password(user, password)
    if user.totp_enabled_at is not None:
        raise ConflictError("La double authentification est déjà activée.")
    secret = pyotp.random_base32()
    user.totp_secret_encrypted = encrypt(secret)
    user.totp_last_used_step = None
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)
    audit_auth_event(session, "auth.mfa_setup_started", user.id, ctx)
    session.commit()
    return MfaSetup(
        secret=secret,
        otpauth_uri=uri,
        qr_svg_data_uri=segno.make(uri, error="m").svg_data_uri(scale=5, border=2),
    )


def enable(
    session: Session, user: User, *, password: str, code: str, ctx: RequestContext
) -> list[str]:
    user = _locked_user(session, user)
    _verify_current_password(user, password)
    if user.totp_enabled_at is not None:
        raise ConflictError("La double authentification est déjà activée.")
    if user.totp_secret_encrypted is None:
        raise BusinessRuleError("Commencez par configurer l'application d'authentification.")
    if not _verify_totp(user, code):
        session.rollback()
        raise InvalidMfaCodeError("Code de vérification incorrect.")
    user.totp_enabled_at = utcnow()
    codes = _new_recovery_codes(session, user)
    audit_auth_event(session, "auth.mfa_enabled", user.id, ctx)
    session.commit()
    return codes


def _check_second_factor(session: Session, user: User, code: str) -> str | None:
    """Accepte un code TOTP ou un code de secours. Renvoie la méthode utilisée."""
    if _verify_totp(user, code):
        return "totp"
    if _consume_recovery_code(session, user, code):
        return "code_secours"
    return None


def complete_login(
    session: Session, *, mfa_token: str, code: str, ctx: RequestContext
) -> TokenPair:
    """Deuxième étape de la connexion : échange le jeton de défi contre une session."""
    settings = get_settings()
    try:
        claims = decode_token(mfa_token, "mfa")
    except InvalidTokenError as exc:
        raise UnauthenticatedError("Délai dépassé. Reconnectez-vous.") from exc
    user = session.execute(
        select(User).where(User.id == claims.user_id).with_for_update()
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.totp_enabled_at is None
        or user.token_version != claims.token_version
    ):
        raise UnauthenticatedError("Délai dépassé. Reconnectez-vous.")

    now = utcnow()
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLockedError(
            "Compte temporairement verrouillé après plusieurs échecs. Réessayez plus tard.",
            headers={"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)},
        )

    method = _check_second_factor(session, user, code)
    if method is None:
        # Les codes erronés comptent dans le même verrouillage que les mots de passe :
        # un code à 6 chiffres ne peut pas être deviné par force brute.
        user.failed_login_count += 1
        audit_auth_event(
            session,
            "auth.mfa_failed",
            user.id,
            ctx,
            {"echecs_consecutifs": user.failed_login_count},
        )
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            user.failed_login_count = 0
            audit_auth_event(
                session,
                "auth.account_locked",
                user.id,
                ctx,
                {"duree_secondes": settings.login_lockout_seconds},
            )
        session.commit()
        raise InvalidMfaCodeError("Code de vérification incorrect.")

    user.failed_login_count = 0
    pair = open_session(session, user, ctx)
    audit_auth_event(session, "auth.login_succeeded", user.id, ctx, {"second_facteur": method})
    session.commit()
    return pair


def disable(session: Session, user: User, *, password: str, code: str, ctx: RequestContext) -> None:
    user = _locked_user(session, user)
    if user.totp_enabled_at is None:
        raise ConflictError("La double authentification n'est pas activée.")
    _verify_current_password(user, password)
    if _check_second_factor(session, user, code) is None:
        session.rollback()
        raise InvalidMfaCodeError("Code de vérification incorrect.")
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.totp_last_used_step = None
    session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    # Désactiver un facteur de sécurité ferme toutes les autres sessions.
    user.token_version += 1
    refresh_tokens.revoke_all(session, user.id)
    audit_auth_event(session, "auth.mfa_disabled", user.id, ctx)
    session.commit()


def regenerate_recovery_codes(
    session: Session, user: User, *, password: str, code: str, ctx: RequestContext
) -> list[str]:
    user = _locked_user(session, user)
    if user.totp_enabled_at is None:
        raise ConflictError("La double authentification n'est pas activée.")
    _verify_current_password(user, password)
    if _check_second_factor(session, user, code) is None:
        session.rollback()
        raise InvalidMfaCodeError("Code de vérification incorrect.")
    codes = _new_recovery_codes(session, user)
    audit_auth_event(session, "auth.mfa_recovery_codes_regenerated", user.id, ctx)
    session.commit()
    return codes
