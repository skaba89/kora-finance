"""Routes du référentiel des tiers : clients et fournisseurs (Phase 4A)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, model_validator

from kora.accounting.entries import Actor
from kora.api.v1.common import WRITE_ERRORS, Limit, Offset, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.core.errors import ErrorResponse
from kora.models.partners import Partner
from kora.partners import service
from kora.partners.service import PartnerData
from kora.tenancy.deps import PartnersManage, PartnersRead, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["tiers"])

KIND = Literal["CLIENT", "FOURNISSEUR"]


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class PartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    is_client: bool
    is_supplier: bool
    tax_id: str | None
    rccm: str | None
    address: str | None
    email: str | None
    phone: str | None
    contact_name: str | None
    default_client_account_id: uuid.UUID | None
    default_supplier_account_id: uuid.UUID | None
    notes: str | None
    is_active: bool
    created_at: str


class PartnersOut(BaseModel):
    items: list[PartnerOut]
    total: int


class PartnerCreate(RequestBody):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    is_client: bool = False
    is_supplier: bool = False
    tax_id: Annotated[str | None, Field(max_length=50)] = None
    rccm: Annotated[str | None, Field(max_length=50)] = None
    address: Annotated[str | None, Field(max_length=300)] = None
    email: Annotated[str | None, Field(max_length=254)] = None
    phone: Annotated[str | None, Field(max_length=30)] = None
    contact_name: Annotated[str | None, Field(max_length=120)] = None
    default_client_account_id: uuid.UUID | None = None
    default_supplier_account_id: uuid.UUID | None = None
    notes: str | None = None
    is_active: bool = True


class PartnerUpdate(RequestBody):
    """PATCH partiel : seuls les champs fournis sont modifiés."""

    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    is_client: bool | None = None
    is_supplier: bool | None = None
    tax_id: Annotated[str | None, Field(max_length=50)] = None
    rccm: Annotated[str | None, Field(max_length=50)] = None
    address: Annotated[str | None, Field(max_length=300)] = None
    email: Annotated[str | None, Field(max_length=254)] = None
    phone: Annotated[str | None, Field(max_length=30)] = None
    contact_name: Annotated[str | None, Field(max_length=120)] = None
    default_client_account_id: uuid.UUID | None = None
    default_supplier_account_id: uuid.UUID | None = None
    notes: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "PartnerUpdate":
        if not self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self


def _out(partner: Partner) -> PartnerOut:
    return PartnerOut(
        id=partner.id,
        name=partner.name,
        is_client=partner.is_client,
        is_supplier=partner.is_supplier,
        tax_id=partner.tax_id,
        rccm=partner.rccm,
        address=partner.address,
        email=partner.email,
        phone=partner.phone,
        contact_name=partner.contact_name,
        default_client_account_id=partner.default_client_account_id,
        default_supplier_account_id=partner.default_supplier_account_id,
        notes=partner.notes,
        is_active=partner.is_active,
        created_at=partner.created_at.isoformat(),
    )


@router.get("/partners", responses={404: {"model": ErrorResponse}})
def list_partners(
    tenant: PartnersRead,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    kind: KIND | None = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> PartnersOut:
    """Référentiel des tiers du dossier, filtrable et paginé."""
    items, total = service.list_partners(
        db,
        tenant.company_id,
        kind=kind,
        active=active,
        search=q,
        limit=limit,
        offset=offset,
    )
    return PartnersOut(items=[_out(p) for p in items], total=total)


@router.post("/partners", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_partner(
    body: PartnerCreate, tenant: PartnersManage, db: DbSession, ctx: Ctx
) -> PartnerOut:
    created = service.create_partner(db, _actor(tenant, ctx), _data(body))
    return _out(created)


@router.get("/partners/{partner_id}", responses={404: {"model": ErrorResponse}})
def get_partner(partner_id: uuid.UUID, tenant: PartnersRead, db: DbSession) -> PartnerOut:
    return _out(service.get_partner(db, tenant.company_id, partner_id))


@router.patch("/partners/{partner_id}", responses=WRITE_ERRORS)
def update_partner(
    partner_id: uuid.UUID,
    body: PartnerUpdate,
    tenant: PartnersManage,
    db: DbSession,
    ctx: Ctx,
) -> PartnerOut:
    changes = body.model_dump(exclude_unset=True)
    return _out(service.update_partner(db, _actor(tenant, ctx), partner_id, changes))


def _data(body: PartnerCreate) -> PartnerData:
    return PartnerData(
        name=body.name,
        is_client=body.is_client,
        is_supplier=body.is_supplier,
        tax_id=body.tax_id,
        rccm=body.rccm,
        address=body.address,
        email=body.email,
        phone=body.phone,
        contact_name=body.contact_name,
        default_client_account_id=body.default_client_account_id,
        default_supplier_account_id=body.default_supplier_account_id,
        notes=body.notes,
        is_active=body.is_active,
    )
