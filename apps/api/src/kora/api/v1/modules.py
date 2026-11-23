"""Configuration plateforme et lecture des capacités d'un dossier."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StrictBool, StrictInt

from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import CurrentUser, DbSession
from kora.tenancy.deps import CompanyRead
from kora.tenancy.module_admin import ModuleClientPage, bind_module_client, list_module_clients
from kora.tenancy.license_query import list_license_periods
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


class LicensePeriodOut(BaseModel):
    id: uuid.UUID
    offer_code: str
    offer_version: int
    kind: str
    starts_on: date
    ends_on: date
    suspended: bool
    status: str


@router.get("/platform/module-clients/{client_id}/licenses", responses=TENANT_ERRORS)
def platform_client_licenses(
    client_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    as_of: date = Query(..., description="Date civile de consultation"),
) -> list[LicensePeriodOut]:
    return [
        LicensePeriodOut.model_validate(row, from_attributes=True)
        for row in list_license_periods(db, actor_id=user.id, company_id=client_id, as_of=as_of)
    ]


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
