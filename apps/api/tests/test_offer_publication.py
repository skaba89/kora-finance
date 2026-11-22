import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import User
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.modules import Module
from kora.tenancy.offer_publication import publish_offer
from kora.tenancy.offers import OfferVersion
from tests.conftest import CompanyFixture, UserFixture


def test_publication_offre_auditee(
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
) -> None:
    company = make_company()
    admin = make_user()
    user = db.get_one(User, admin.id)
    user.is_platform_admin = True
    db.commit()
    code = f"test-{uuid.uuid4().hex}"
    offer = OfferVersion(code=code, version=1, modules=frozenset({Module.SALES}))
    with pytest.raises(ForbiddenError):
        publish_offer(db, actor_id=company.owner.id, offer=offer)
    bind_tenant(db, company.id)
    with pytest.raises(ForbiddenError):
        publish_offer(db, actor_id=admin.id, offer=offer)
    bind_tenant(db, None)
    with pytest.raises(BusinessRuleError):
        publish_offer(
            db,
            actor_id=admin.id,
            offer=OfferVersion(code="x" * 65, version=1, modules=offer.modules),
        )
    publish_offer(db, actor_id=admin.id, offer=offer)
    row = db.get_one(CommercialOfferVersion, (code, 1))
    assert row.modules == ["sales"]
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id.is_(None),
            AuditEvent.action == "commercial.offer_published",
            AuditEvent.entity_id == f"{code}:1",
        )
    )
    assert event is not None
    assert event.actor_user_id == admin.id
    assert event.payload == {"code": code, "version": 1, "modules": ["sales"]}
    assert verify_chain(db).ok
    with pytest.raises(ConflictError):
        publish_offer(db, actor_id=admin.id, offer=offer)
    db.rollback()
    assert db.get(CommercialOfferVersion, (code, 1)) is None
    user.is_active = False
    db.commit()
    with pytest.raises(ForbiddenError):
        publish_offer(db, actor_id=admin.id, offer=offer)
