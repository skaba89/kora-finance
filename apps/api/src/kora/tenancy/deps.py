"""Dépendances FastAPI de contexte tenant et de permissions.

Toute route sous `/companies/{company_id}/…` doit passer par `require(permission)`.
Le test `test_isolation_tenants.py` vérifie automatiquement qu'aucune route de ce type
ne répond autre chose que 404 à un utilisateur sans accès au dossier.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path

from kora.auth.deps import CurrentUser, DbSession
from kora.core.errors import ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.identity import User
from kora.tenancy.access import resolve_role
from kora.tenancy.permissions import Permission, permissions_for
from kora.tenancy.roles import Role


@dataclass(frozen=True)
class TenantContext:
    company_id: uuid.UUID
    user: User
    role: Role
    permissions: frozenset[Permission]


def get_tenant(
    company_id: Annotated[uuid.UUID, Path(description="Identifiant du dossier d'entreprise")],
    user: CurrentUser,
    db: DbSession,
) -> TenantContext:
    role = resolve_role(db, user, company_id)
    if role is None:
        # 404 et non 403 : on ne révèle pas l'existence d'un dossier inaccessible.
        raise NotFoundError("Dossier introuvable.")
    bind_tenant(db, company_id)
    return TenantContext(company_id, user, role, permissions_for(role))


def require(permission: Permission) -> Callable[..., TenantContext]:
    def dependency(tenant: Annotated[TenantContext, Depends(get_tenant)]) -> TenantContext:
        if permission not in tenant.permissions:
            raise ForbiddenError("Votre rôle ne permet pas cette action.")
        return tenant

    dependency.__name__ = f"require_{permission.value.replace(':', '_')}"
    return dependency


# Contexte tenant exigeant une permission donnée, à utiliser comme type de paramètre.
CompanyRead = Annotated[TenantContext, Depends(require(Permission.COMPANY_READ))]
CompanyUpdate = Annotated[TenantContext, Depends(require(Permission.COMPANY_UPDATE))]
MembersRead = Annotated[TenantContext, Depends(require(Permission.MEMBERS_READ))]
MembersManage = Annotated[TenantContext, Depends(require(Permission.MEMBERS_MANAGE))]
FiscalYearsRead = Annotated[TenantContext, Depends(require(Permission.FISCAL_YEARS_READ))]
FiscalYearsManage = Annotated[TenantContext, Depends(require(Permission.FISCAL_YEARS_MANAGE))]
AccountsRead = Annotated[TenantContext, Depends(require(Permission.ACCOUNTS_READ))]
AccountsManage = Annotated[TenantContext, Depends(require(Permission.ACCOUNTS_MANAGE))]
TaxesRead = Annotated[TenantContext, Depends(require(Permission.TAXES_READ))]
TaxesManage = Annotated[TenantContext, Depends(require(Permission.TAXES_MANAGE))]
AuditRead = Annotated[TenantContext, Depends(require(Permission.AUDIT_READ))]
