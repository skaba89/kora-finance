"""Persistance interne de la configuration ; aucune route HTTP au lot M2."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.config import get_settings
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import current_tenant
from kora.models.common import utcnow
from kora.models.identity import Company, User
from kora.models.modules import TenantModuleOverride
from kora.tenancy.modules import CATALOG, Module, ModuleStatus, resolve_modules


def _require_tenant(session: Session, company_id: uuid.UUID) -> None:
    if current_tenant(session) != company_id:
        raise ForbiddenError("Contexte du dossier obligatoire.")


@dataclass(frozen=True)
class ModuleConfiguration:
    module: Module
    released: bool
    default_enabled: bool
    dependencies: tuple[Module, ...]
    configured_enabled: bool | None
    revision: int
    configured_status: ModuleStatus


def module_configuration(session: Session, company_id: uuid.UUID) -> list[ModuleConfiguration]:
    """Instantané cohérent : état calculé et choix explicite dans la même lecture."""
    _require_tenant(session, company_id)
    rows = session.scalars(
        select(TenantModuleOverride)
        .where(TenantModuleOverride.tenant_id == company_id)
        .execution_options(populate_existing=True)
    )
    overrides = {Module(row.module): (row.enabled, row.revision) for row in rows}
    statuses = resolve_modules({module: choice[0] for module, choice in overrides.items()})
    return [
        ModuleConfiguration(
            module=module,
            released=definition.released,
            default_enabled=definition.default_enabled,
            dependencies=tuple(sorted(definition.dependencies)),
            configured_enabled=overrides[module][0] if module in overrides else None,
            revision=overrides[module][1] if module in overrides else 0,
            configured_status=statuses[module],
        )
        for module, definition in CATALOG.items()
    ]


def effective_modules(session: Session, company_id: uuid.UUID) -> dict[Module, ModuleStatus]:
    """Lecture interne, dans un contexte tenant déjà autorisé par l'appelant."""
    return {row.module: row.configured_status for row in module_configuration(session, company_id)}


def require_enabled_module(session: Session, company_id: uuid.UUID, module: Module) -> None:
    """Garde complémentaire au RBAC, après autorisation et liaison du tenant."""
    if effective_modules(session, company_id)[module] != ModuleStatus.ENABLED:
        raise ForbiddenError("Ce module n'est pas actif pour ce dossier.")


def require_platform_admin(session: Session, actor_id: uuid.UUID) -> None:
    """Vérifie le droit courant en base, sans accorder un rôle sur un dossier."""
    admin = session.scalar(
        select(User).where(User.id == actor_id, User.is_active, User.is_platform_admin)
    )
    if admin is None:
        raise ForbiddenError("Administration de la plateforme requise.")
    if get_settings().platform_admin_require_mfa and admin.totp_enabled_at is None:
        raise ForbiddenError(
            "Double authentification requise pour l'administration de la plateforme."
        )


def set_module_override(
    session: Session,
    company_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    module: Module,
    enabled: bool,
    expected_revision: int,
) -> int:
    """Enregistre un choix sous verrou ; l'appelant possède la transaction.

    Révision 0 = choix absent. Aucun changement n'est appliqué aux droits métier.
    Le journal d'audit et le choix sont atomiques avec le commit de l'appelant.
    """
    _require_tenant(session, company_id)
    require_platform_admin(session, actor_id)
    if module not in CATALOG or (enabled and not CATALOG[module].released):
        raise BusinessRuleError("Module non disponible.")
    company = session.scalar(select(Company.id).where(Company.id == company_id).with_for_update())
    if company is None:
        raise NotFoundError("Dossier introuvable.")
    row = session.scalar(
        select(TenantModuleOverride)
        .where(
            TenantModuleOverride.tenant_id == company_id,
            TenantModuleOverride.module == module.value,
        )
        .execution_options(populate_existing=True)
    )
    revision = row.revision if row is not None else 0
    if revision != expected_revision:
        raise ConflictError("Configuration modifiée ; actualisez avant de réessayer.")
    if row is not None and row.enabled == enabled:
        return revision
    previous = row.enabled if row is not None else None
    revision += 1
    if row is None:
        row = TenantModuleOverride(tenant_id=company_id, module=module.value)
        session.add(row)
    row.enabled = enabled
    row.revision = revision
    row.updated_by_user_id = actor_id
    row.updated_at = utcnow()
    record_event(
        session,
        action="module.configuration_changed",
        entity_type="module",
        entity_id=module.value,
        actor_user_id=actor_id,
        payload={"previous": previous, "enabled": enabled, "revision": revision},
    )
    return revision
