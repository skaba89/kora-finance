import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.core.errors import ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.license_assignment import assign_license
from kora.tenancy.licenses import LicenseKind, LicensePeriod
from tests.conftest import CompanyFixture, UserFixture


def test_attribution_licence_auditee_et_sans_chevauchement(
    db: Session,
    owner_engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.commit()
    period = LicensePeriod(
        tenant_id=company.id, offer_code=code, offer_version=1,
        kind=LicenseKind.TRIAL,
        starts_on=date(2027, 1, 1), ends_on=date(2027, 2, 1),
    )
    with pytest.raises(ForbiddenError):
        assign_license(db, actor_id=other.owner.id, period=period)
    bind_tenant(db, other.id)
    with pytest.raises(ForbiddenError):
        assign_license(db, actor_id=admin.id, period=period)
    bind_tenant(db, None)
    assigned_id = assign_license(db, actor_id=admin.id, period=period)
    assert db.get_one(CommercialLicensePeriod, assigned_id).kind == "trial"
    assert db.scalar(select(AuditEvent).where(
        AuditEvent.action == "commercial.license_assigned",
        AuditEvent.entity_id == str(assigned_id),
        AuditEvent.tenant_id == company.id,
    )) is not None
    assert verify_chain(db).ok
    bind_tenant(db, None)
    with pytest.raises(ConflictError):
        assign_license(db, actor_id=admin.id, period=period)
    bind_tenant(db, None)
    adjacent = LicensePeriod(
        tenant_id=company.id, offer_code=code, offer_version=1,
        kind=LicenseKind.PAID,
        starts_on=date(2027, 2, 1), ends_on=date(2027, 3, 1),
    )
    assign_license(db, actor_id=admin.id, period=adjacent)
    db.rollback()
    bind_tenant(db, company.id)
    assert db.get(CommercialLicensePeriod, assigned_id) is None


def test_licence_runtime_insert_seul(db: Session) -> None:
    rights = db.execute(text("""
        SELECT has_table_privilege('commercial_license_periods', 'SELECT'),
               has_table_privilege('commercial_license_periods', 'INSERT'),
               has_table_privilege('commercial_license_periods', 'UPDATE'),
               has_table_privilege('commercial_license_periods', 'DELETE')
    """)).one()
    assert tuple(rights) == (True, True, False, False)


def test_offre_inexistante_refusee(
    db: Session,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, admin = make_company(), make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    with pytest.raises(NotFoundError):
        assign_license(
            db, actor_id=admin.id,
            period=LicensePeriod(
                tenant_id=company.id, offer_code=f"missing-{uuid.uuid4().hex}",
                offer_version=1, kind=LicenseKind.PAID,
                starts_on=date(2027, 4, 1), ends_on=date(2027, 5, 1),
            ),
        )
