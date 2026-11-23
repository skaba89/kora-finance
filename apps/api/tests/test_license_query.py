import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from kora.core.errors import BusinessRuleError, ForbiddenError
from kora.db.tenant import bind_tenant
from kora.models.identity import User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.license_query import list_license_periods
from kora.tenancy.licenses import LicenseKind, LicenseStatus
from tests.conftest import CompanyFixture, UserFixture


def test_consultation_licences_statuts_et_isolation(
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        bind_tenant(owner, company.id)
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.add(
            CommercialLicensePeriod(
                tenant_id=company.id,
                offer_code=code,
                offer_version=1,
                kind="trial",
                starts_on=date(2027, 1, 1),
                ends_on=date(2027, 2, 1),
            )
        )
        owner.add(
            CommercialLicensePeriod(
                tenant_id=company.id,
                offer_code=code,
                offer_version=1,
                kind="paid",
                starts_on=date(2027, 2, 1),
                ends_on=date(2027, 3, 1),
                suspended=True,
            )
        )
        owner.commit()
    with pytest.raises(ForbiddenError):
        list_license_periods(
            db,
            actor_id=other.owner.id,
            company_id=company.id,
            as_of=date(2027, 1, 15),
        )
    bind_tenant(db, other.id)
    with pytest.raises(ForbiddenError):
        list_license_periods(
            db,
            actor_id=admin.id,
            company_id=company.id,
            as_of=date(2027, 1, 15),
        )
    bind_tenant(db, None)
    jan = list_license_periods(
        db, actor_id=admin.id, company_id=company.id, as_of=date(2027, 1, 15)
    )
    assert [row.status for row in jan] == [LicenseStatus.TRIAL, LicenseStatus.SCHEDULED]
    assert [row.kind for row in jan] == [LicenseKind.TRIAL, LicenseKind.PAID]
    bind_tenant(db, None)
    feb = list_license_periods(db, actor_id=admin.id, company_id=company.id, as_of=date(2027, 2, 1))
    assert [row.status for row in feb] == [LicenseStatus.EXPIRED, LicenseStatus.SUSPENDED]
    bind_tenant(db, None)
    assert (
        list_license_periods(db, actor_id=admin.id, company_id=other.id, as_of=date(2027, 2, 1))
        == []
    )


def test_consultation_refuse_date_invalide(
    db: Session,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, admin = make_company(), make_user()
    with pytest.raises(BusinessRuleError):
        list_license_periods(
            db,
            actor_id=admin.id,
            company_id=company.id,
            as_of="2027-01-01",  # type: ignore[arg-type]
        )
