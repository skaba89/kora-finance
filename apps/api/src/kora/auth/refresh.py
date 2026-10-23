"""Refresh tokens opaques avec rotation et détection de réutilisation.

Chaque connexion ouvre une *famille*. Chaque rafraîchissement consomme le jeton
présenté et en émet un nouveau dans la même famille. Si un jeton déjà consommé est
présenté de nouveau, c'est qu'il a été copié : toute la famille est révoquée.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.models.common import utcnow
from kora.models.identity import RefreshToken, User


class RefreshError(Exception):
    def __init__(
        self, reason: str, *, reuse_detected: bool = False, user_id: uuid.UUID | None = None
    ):
        super().__init__(reason)
        self.reuse_detected = reuse_detected
        self.user_id = user_id


@dataclass(frozen=True)
class IssuedRefreshToken:
    token: str
    family_id: uuid.UUID


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(
    session: Session,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedRefreshToken:
    token = secrets.token_urlsafe(32)
    family = family_id or uuid.uuid4()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family,
            token_hash=_hash(token),
            expires_at=utcnow() + timedelta(days=get_settings().refresh_token_ttl_days),
            user_agent=(user_agent or "")[:300] or None,
            ip_address=ip_address,
        )
    )
    session.flush()
    return IssuedRefreshToken(token=token, family_id=family)


def revoke_family(session: Session, family_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def revoke_all(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def consume(session: Session, token: str) -> RefreshToken:
    """Valide et consomme un refresh token. Lève RefreshError sinon.

    La ligne est verrouillée : deux rafraîchissements simultanés du même jeton ne
    peuvent pas réussir tous les deux.
    """
    record = session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(token)).with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise RefreshError("jeton inconnu")
    if record.used_at is not None:
        # Réutilisation d'un jeton déjà consommé : vol présumé, on coupe toute la famille.
        revoke_family(session, record.family_id)
        raise RefreshError("jeton déjà utilisé", reuse_detected=True, user_id=record.user_id)
    if record.revoked_at is not None:
        raise RefreshError("jeton révoqué", user_id=record.user_id)
    if record.expires_at <= utcnow():
        raise RefreshError("jeton expiré", user_id=record.user_id)
    record.used_at = utcnow()
    return record


def find_family(session: Session, token: str) -> RefreshToken | None:
    return session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(token))
    ).scalar_one_or_none()
