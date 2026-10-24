"""Invitations : donner accès à un dossier à une personne qui n'a pas encore de compte.

Ajouter un membre dont l'adresse a déjà un compte le rattache immédiatement ; sinon,
une invitation est créée et envoyée par email (par le worker). L'invité choisit son
nom et son mot de passe ; son adresse est vérifiée de fait puisqu'il a reçu le lien.

Anti-abus : seul un utilisateur à l'adresse vérifiée peut inviter, et le nombre
d'emails d'invitation par dossier est plafonné sur 24 heures.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth.one_time import new_token, token_hash
from kora.auth.passwords import hash_password
from kora.auth.service import (
    RequestContext,
    audit_auth_event,
    check_password_policy,
    get_user_by_email,
    normalize_email,
)
from kora.core.config import get_settings
from kora.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidLinkError,
    NotFoundError,
    TooManyRequestsError,
)
from kora.db.tenant import bind_tenant
from kora.email import quota, templates
from kora.email.sender import OutgoingEmail
from kora.models.common import utcnow
from kora.models.identity import Company, CompanyMembership, Invitation, User
from kora.organization.service import MemberRow, TenantLike, add_member, check_company_role

_INVALID = "Cette invitation est invalide, a expiré ou a été annulée."


class EmailNotVerifiedError(ForbiddenError):
    code = "email_non_verifie"


@dataclass(frozen=True)
class InvitationPreview:
    email: str
    company_name: str
    role: str
    inviter_name: str
    account_exists: bool


def company_display_name(company: Company) -> str:
    return company.trade_name or company.legal_name


def _check_invitation_quota(company_id: uuid.UUID) -> None:
    limit = get_settings().invitations_per_company_per_day
    if not quota.allowed("invitation", str(company_id), limit=limit, window_seconds=quota.DAY):
        raise TooManyRequestsError(
            f"Limite de {limit} invitations par jour atteinte pour ce dossier.",
            headers={"Retry-After": quota.retry_after(quota.DAY)},
        )


def _audit_tenant(
    session: Session,
    company_id: uuid.UUID,
    *,
    action: str,
    invitation: Invitation,
    actor_user_id: uuid.UUID,
    ctx: RequestContext,
    payload: dict[str, str | None] | None = None,
) -> None:
    bind_tenant(session, company_id)
    record_event(
        session,
        action=action,
        entity_type="invitation",
        entity_id=invitation.id,
        payload={"email": invitation.email, "role": invitation.role, **(payload or {})},
        actor_user_id=actor_user_id,
        ip_address=ctx.ip_address,
    )


def add_member_or_invite(
    session: Session,
    tenant: TenantLike,
    inviter: User,
    *,
    email: str,
    role: str,
    ctx: RequestContext,
) -> MemberRow | Invitation:
    email = normalize_email(email)
    company_role = check_company_role(role)
    if get_user_by_email(session, email) is not None:
        return add_member(session, tenant, email=email, role=company_role, ctx=ctx)

    if inviter.email_verified_at is None:
        raise EmailNotVerifiedError(
            "Confirmez d'abord votre propre adresse email pour pouvoir inviter quelqu'un."
        )
    now = utcnow()
    pending = session.execute(
        select(Invitation)
        .where(
            Invitation.company_id == tenant.company_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if pending is not None and pending.expires_at > now:
        raise ConflictError(
            "Une invitation est déjà en attente pour cette adresse. Vous pouvez la renvoyer."
        )
    _check_invitation_quota(tenant.company_id)
    expires_at = now + timedelta(days=get_settings().invitation_ttl_days)
    if pending is not None:
        # Invitation expirée : elle est renouvelée plutôt que dupliquée.
        invitation = pending
        invitation.role = company_role
        invitation.invited_by_user_id = inviter.id
        invitation.expires_at = expires_at
        invitation.token_hash = None
    else:
        invitation = Invitation(
            company_id=tenant.company_id,
            email=email,
            role=company_role,
            invited_by_user_id=inviter.id,
            locale=inviter.locale,
            expires_at=expires_at,
        )
        session.add(invitation)
    session.flush()
    _audit_tenant(
        session,
        tenant.company_id,
        action="invitation.created",
        invitation=invitation,
        actor_user_id=inviter.id,
        ctx=ctx,
    )
    session.commit()
    return invitation


def list_pending(session: Session, company_id: uuid.UUID) -> list[Invitation]:
    return list(
        session.execute(
            select(Invitation)
            .where(
                Invitation.company_id == company_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .order_by(Invitation.created_at.desc())
        ).scalars()
    )


def _get_pending(session: Session, tenant: TenantLike, invitation_id: uuid.UUID) -> Invitation:
    # Filtre explicite sur le dossier : une invitation d'un autre dossier est introuvable.
    invitation = session.execute(
        select(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.company_id == tenant.company_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if invitation is None:
        raise NotFoundError("Invitation introuvable.")
    return invitation


def resend(
    session: Session, tenant: TenantLike, invitation_id: uuid.UUID, ctx: RequestContext
) -> Invitation:
    invitation = _get_pending(session, tenant, invitation_id)
    _check_invitation_quota(tenant.company_id)
    invitation.expires_at = utcnow() + timedelta(days=get_settings().invitation_ttl_days)
    invitation.token_hash = None
    _audit_tenant(
        session,
        tenant.company_id,
        action="invitation.resent",
        invitation=invitation,
        actor_user_id=tenant.user_id,
        ctx=ctx,
    )
    session.commit()
    return invitation


def revoke(
    session: Session, tenant: TenantLike, invitation_id: uuid.UUID, ctx: RequestContext
) -> None:
    invitation = _get_pending(session, tenant, invitation_id)
    invitation.revoked_at = utcnow()
    invitation.token_hash = None
    _audit_tenant(
        session,
        tenant.company_id,
        action="invitation.revoked",
        invitation=invitation,
        actor_user_id=tenant.user_id,
        ctx=ctx,
    )
    session.commit()


# --- Envoi (worker)


def prepare_email(session: Session, invitation_id: uuid.UUID) -> OutgoingEmail | None:
    """Génère un nouveau lien (le précédent cesse de fonctionner) et l'email à envoyer."""
    invitation = session.get(Invitation, invitation_id, with_for_update=True)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= utcnow()
    ):
        return None
    company = session.get(Company, invitation.company_id)
    inviter = session.get(User, invitation.invited_by_user_id)
    if company is None or inviter is None:
        return None
    token, digest = new_token()
    invitation.token_hash = digest
    invitation.sent_at = utcnow()
    session.commit()
    locale = invitation.locale
    return templates.render(
        "invitation",
        locale,
        to=invitation.email,
        url=f"{get_settings().web_public_url}/{locale}/invitation?jeton={token}",
        inviter=inviter.full_name,
        company=company_display_name(company),
        role=templates.ROLE_LABELS.get(locale, templates.ROLE_LABELS["fr"])[invitation.role],
        ttl=get_settings().invitation_ttl_days,
    )


# --- Acceptation


def _find_valid(session: Session, token: str, *, lock: bool) -> Invitation:
    query = select(Invitation).where(Invitation.token_hash == token_hash(token))
    invitation = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= utcnow()
    ):
        raise InvalidLinkError(_INVALID)
    return invitation


def preview(session: Session, token: str) -> InvitationPreview:
    invitation = _find_valid(session, token, lock=False)
    company = session.get(Company, invitation.company_id)
    inviter = session.get(User, invitation.invited_by_user_id)
    if company is None or inviter is None:
        raise InvalidLinkError(_INVALID)
    return InvitationPreview(
        email=invitation.email,
        company_name=company_display_name(company),
        role=invitation.role,
        inviter_name=inviter.full_name,
        account_exists=get_user_by_email(session, invitation.email) is not None,
    )


def _join(
    session: Session, invitation: Invitation, user: User, ctx: RequestContext
) -> CompanyMembership:
    now = utcnow()
    invitation.accepted_at = now
    invitation.accepted_user_id = user.id
    invitation.token_hash = None
    # Le lien a été reçu à cette adresse : elle est vérifiée de fait.
    user.email_verified_at = user.email_verified_at or now
    membership = session.execute(
        select(CompanyMembership).where(
            CompanyMembership.company_id == invitation.company_id,
            CompanyMembership.user_id == user.id,
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = CompanyMembership(
            company_id=invitation.company_id, user_id=user.id, role=invitation.role
        )
        session.add(membership)
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError as exc:
            raise ConflictError("Cette personne a déjà accès au dossier.") from exc
    _audit_tenant(
        session,
        invitation.company_id,
        action="invitation.accepted",
        invitation=invitation,
        actor_user_id=user.id,
        ctx=ctx,
        payload={"user_id": str(user.id), "membership_id": str(membership.id)},
    )
    return membership


def accept_with_new_account(
    session: Session, *, token: str, full_name: str, password: str, ctx: RequestContext
) -> tuple[User, uuid.UUID]:
    invitation = _find_valid(session, token, lock=True)
    if get_user_by_email(session, invitation.email) is not None:
        session.rollback()
        raise ConflictError(
            "Un compte existe déjà avec cette adresse : connectez-vous pour accepter l'invitation."
        )
    check_password_policy(password, invitation.email)
    user = User(
        email=invitation.email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        locale=invitation.locale,
    )
    session.add(user)
    session.flush()
    audit_auth_event(session, "user.registered", user.id, ctx, {"via_invitation": True})
    _join(session, invitation, user, ctx)
    company_id = invitation.company_id
    session.commit()
    return user, company_id


def accept_as(session: Session, user: User, *, token: str, ctx: RequestContext) -> uuid.UUID:
    """Acceptation par un utilisateur connecté, dont l'adresse doit être celle invitée."""
    invitation = _find_valid(session, token, lock=True)
    if invitation.email != user.email:
        session.rollback()
        # Même réponse qu'un lien inconnu : ne pas révéler l'invitation d'un tiers.
        raise InvalidLinkError(_INVALID)
    _join(session, invitation, user, ctx)
    company_id = invitation.company_id
    session.commit()
    return company_id
