"""Persistance contrôlée des renouvellements sans altérer les périodes existantes."""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.license_renewal_assignment import renew_license
from tests.conftest import CompanyFixture, UserFixture


def test_renouvellement_persiste_adjacent_audite_et_rollback(
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    previous_id = uuid.uuid4()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        bind_tenant(owner, company.id)
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.flush()
        owner.add(
            CommercialLicensePeriod(
                id=previous_id,
                tenant_id=company.id,
                offer_code=code,
                offer_version=1,
                kind="trial",
                starts_on=date(2027, 1, 1),
                ends_on=date(2027, 2, 1),
            )
        )
        owner.commit()

    args = {
        "company_id": company.id,
        "previous_id": previous_id,
        "ends_on": date(2027, 3, 1),
    }
    with pytest.raises(ForbiddenError):
        renew_license(db, actor_id=other.owner.id, **args)
    bind_tenant(db, other.id)
    with pytest.raises(ForbiddenError):
        renew_license(db, actor_id=admin.id, **args)
    bind_tenant(db, None)
    with pytest.raises(NotFoundError):
        renew_license(
            db,
            actor_id=admin.id,
            company_id=other.id,
            previous_id=previous_id,
            ends_on=date(2027, 3, 1),
        )
    bind_tenant(db, None)
    new_id = renew_license(db, actor_id=admin.id, **args)
    renewed = db.get_one(CommercialLicensePeriod, new_id)
    previous = db.get_one(CommercialLicensePeriod, previous_id)
    assert renewed.starts_on == previous.ends_on
    assert renewed.ends_on == date(2027, 3, 1)
    assert renewed.kind == "paid"
    assert previous.kind == "trial"
    assert previous.ends_on == date(2027, 2, 1)
    assert verify_chain(db).ok
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "commercial.license_assigned",
            AuditEvent.entity_id == str(new_id),
            AuditEvent.tenant_id == company.id,
        )
    ) is not None
    bind_tenant(db, None)
    with pytest.raises(ConflictError):
        renew_license(db, actor_id=admin.id, **args)
    db.rollback()
    bind_tenant(db, company.id)
    assert db.get(CommercialLicensePeriod, new_id) is None


def test_renouvellement_refuse_date_invalide_avant_acces(db: Session) -> None:
    with pytest.raises(BusinessRuleError):
        renew_license(
            db,
            actor_id=uuid.uuid4(),
            company_id=uuid.uuid4(),
            previous_id=uuid.uuid4(),
            ends_on=date(2026, 1, 1),
            kind="paid",  # type: ignore[arg-type]
        )
