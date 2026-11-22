"""Configuration plateforme et lecture des capacités d'un dossier."""

import uuid
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictBool, StrictInt

from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import CurrentUser, DbSession
from kora.tenancy.deps import CompanyRead
from kora.tenancy.module_admin import ModuleClientPage, bind_module_client, list_module_clients
from kora.tenancy.module_config import (
    ModuleConfiguration,
    module_configuration,
    set_module_override,
)
from kora.tenancy.modules import Module, ModuleStatus

router = APIRouter(tags=["modules"])


class ModuleOverrideIn(RequestBody):
    enabled: StrictBool
    expected_revision: Annotated[StrictInt, Field(ge=0, le=2147483646)]


class ModuleCapability(BaseModel):
    module: Module
    configured_status: ModuleStatus


@router.get("/platform/module-clients", responses=TENANT_ERRORS)
def platform_module_clients(
    user: CurrentUser, db: DbSession, limit: Limit = 50, offset: Offset = 0
) -> ModuleClientPage:
    return list_module_clients(db, user.id, limit=limit, offset=offset)


@router.get("/platform/module-clients/{client_id}/modules", responses=TENANT_ERRORS)
def platform_module_configuration(
    client_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[ModuleConfiguration]:
    bind_module_client(db, user.id, client_id)
    return module_configuration(db, client_id)


@router.put("/platform/module-clients/{client_id}/modules/{module}", responses=WRITE_ERRORS)
def platform_module_update(
    client_id: uuid.UUID, module: Module, body: ModuleOverrideIn, user: CurrentUser, db: DbSession
) -> list[ModuleConfiguration]:
    bind_module_client(db, user.id, client_id)
    set_module_override(
        db,
        client_id,
        actor_id=user.id,
        module=module,
        enabled=body.enabled,
        expected_revision=body.expected_revision,
    )
    configuration = module_configuration(db, client_id)
    db.commit()
    return configuration


@router.get("/companies/{company_id}/module-capabilities", responses=TENANT_ERRORS)
def company_module_capabilities(tenant: CompanyRead, db: DbSession) -> list[ModuleCapability]:
    return [
        ModuleCapability(module=row.module, configured_status=row.configured_status)
        for row in module_configuration(db, tenant.company_id)
    ]
