"""Consultation commerciale par dossier, sans modifier les droits métier."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.core.errors import BusinessRuleError
from kora.models.licenses import CommercialLicensePeriod
from kora.tenancy.licenses import LicenseKind, LicensePeriod, LicenseStatus
from kora.tenancy.module_admin import bind_module_client


@dataclass(frozen=True, slots=True)
class LicenseSnapshot:
    id: uuid.UUID
    offer_code: str
    offer_version: int
    kind: LicenseKind
    starts_on: date
    ends_on: date
    suspended: bool
    status: LicenseStatus


def list_license_periods(
    session: Session,
    *,
    actor_id: uuid.UUID,
    company_id: uuid.UUID,
    as_of: date,
) -> list[LicenseSnapshot]:
    """Lit un seul dossier sous RLS après vérification de l'admin plateforme.

    La date est explicite ; l'API ne dépend pas d'une horloge implicite.
    La session doit être dédiée à ce dossier, comme pour assign_license.
    """
    if type(as_of) is not date:
        raise BusinessRuleError("Date civile requise.")
    bind_module_client(session, actor_id, company_id)
    rows = session.scalars(
        select(CommercialLicensePeriod)
        .where(CommercialLicensePeriod.tenant_id == company_id)
        .order_by(CommercialLicensePeriod.starts_on, CommercialLicensePeriod.id)
    ).all()
    result: list[LicenseSnapshot] = []
    for row in rows:
        period = LicensePeriod(
            tenant_id=row.tenant_id,
            offer_code=row.offer_code,
            offer_version=row.offer_version,
            kind=LicenseKind(row.kind),
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            suspended=row.suspended,
        )
        result.append(
            LicenseSnapshot(
                id=row.id,
                offer_code=row.offer_code,
                offer_version=row.offer_version,
                kind=period.kind,
                starts_on=period.starts_on,
                ends_on=period.ends_on,
                suspended=period.suspended,
                status=period.status_on(as_of),
            )
        )
    return result
