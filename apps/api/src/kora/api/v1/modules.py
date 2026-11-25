"""Configuration plateforme et lecture des capacités d'un dossier."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, BeforeValidator, Field, StrictBool, StrictInt, StringConstraints

from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import CurrentUser, DbSession
from kora.models.licenses import CommercialLicensePeriod
from kora.tenancy.deps import CompanyRead
from kora.tenancy.license_query import list_license_periods
from kora.tenancy.license_renewal_assignment import renew_license
from kora.tenancy.license_suspension import (
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    change_license_suspension,
)
from kora.tenancy.licenses import LicenseKind
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


# Motif d'intervention commerciale : mêmes bornes que le service.
Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH
    ),
]


class LicenseSuspensionIn(RequestBody):
    suspended: StrictBool
    expected_suspended: StrictBool
    reason: Reason


def _iso_date_only(value: object) -> object:
    """Refuse les horodatages numériques que le mode souple convertirait en date."""
    if not isinstance(value, str | date):
        raise ValueError("Date civile AAAA-MM-JJ attendue.")
    return value


class LicenseRenewalIn(RequestBody):
    ends_on: Annotated[
        date,
        BeforeValidator(_iso_date_only),
        Field(description="Fin exclusive (AAAA-MM-JJ)"),
    ]
    kind: LicenseKind
    reason: Reason


class LicenseRenewalOut(BaseModel):
    id: uuid.UUID
    starts_on: date
    ends_on: date
    kind: LicenseKind


class LicenseSuspensionOut(BaseModel):
    id: uuid.UUID
    suspended: bool
    changed: bool


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
    as_of: Annotated[date, Query(description="Date civile de consultation")],
) -> list[LicensePeriodOut]:
    return [
        LicensePeriodOut.model_validate(row, from_attributes=True)
        for row in list_license_periods(db, actor_id=user.id, company_id=client_id, as_of=as_of)
    ]


@router.put(
    "/platform/module-clients/{client_id}/licenses/{license_id}/suspension",
    responses=WRITE_ERRORS,
)
def platform_license_suspension(
    client_id: uuid.UUID,
    license_id: uuid.UUID,
    body: LicenseSuspensionIn,
    user: CurrentUser,
    db: DbSession,
) -> LicenseSuspensionOut:
    """Suspend ou réactive une période commerciale, sans effet sur paiements ou droits comptables.

    `expected_suspended` rejette (409) une demande fondée sur un état obsolète.
    Le changement et son audit (avec motif) sont validés dans une seule transaction.
    """
    changed = change_license_suspension(
        db,
        actor_id=user.id,
        company_id=client_id,
        license_id=license_id,
        suspended=body.suspended,
        expected_suspended=body.expected_suspended,
        reason=body.reason,
    )
    db.commit()
    return LicenseSuspensionOut(id=license_id, suspended=body.suspended, changed=changed)


@router.post(
    "/platform/module-clients/{client_id}/licenses/{license_id}/renewals",
    responses=WRITE_ERRORS,
    status_code=status.HTTP_201_CREATED,
)
def platform_license_renewal(
    client_id: uuid.UUID,
    license_id: uuid.UUID,
    body: LicenseRenewalIn,
    user: CurrentUser,
    db: DbSession,
) -> LicenseRenewalOut:
    """Ajoute une période adjacente ; l'ancienne reste inchangée.

    422 : période suspendue, fin non postérieure ou début dans le passé.
    409 : chevauchement (dont double envoi). Aucun paiement ni droit comptable.
    """
    new_id = renew_license(
        db,
        actor_id=user.id,
        company_id=client_id,
        previous_id=license_id,
        ends_on=body.ends_on,
        kind=body.kind,
        reason=body.reason,
    )
    period = db.get_one(CommercialLicensePeriod, new_id)
    result = LicenseRenewalOut(
        id=new_id, starts_on=period.starts_on, ends_on=period.ends_on, kind=LicenseKind(period.kind)
    )
    db.commit()
    return result


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
