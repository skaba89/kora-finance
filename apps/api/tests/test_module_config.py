from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.common import utcnow
from kora.models.identity import User
from kora.models.modules import TenantModuleOverride
from kora.tenancy.module_config import effective_modules, set_module_override
from kora.tenancy.modules import Module, ModuleStatus
from tests.conftest import CompanyFixture, UserFixture


def test_module_configuration(
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
) -> None:
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    first = make_company()
    second = make_company()
    with pytest.raises(ForbiddenError):
        effective_modules(db, first.id)
    bind_tenant(db, first.id)
    assert effective_modules(db, first.id)[Module.TREASURY] == ModuleStatus.ENABLED

    def configure(enabled: bool, revision: int, module: Module = Module.TREASURY) -> int:
        return set_module_override(
            db,
            first.id,
            actor_id=admin.id,
            module=module,
            enabled=enabled,
            expected_revision=revision,
        )

    with pytest.raises(ForbiddenError):
        set_module_override(
            db,
            first.id,
            actor_id=first.owner.id,
            module=Module.TREASURY,
            enabled=False,
            expected_revision=0,
        )
    with pytest.raises(BusinessRuleError):
        configure(True, 0, Module.OCR)
    assert configure(False, 0) == 1
    db.commit()
    assert effective_modules(db, first.id)[Module.FORECAST] == ModuleStatus.DEPENDENCY_DISABLED
    with pytest.raises(ConflictError):
        configure(True, 0)
    assert configure(False, 1) == 1
    assert configure(True, 1) == 2
    db.rollback()
    assert effective_modules(db, first.id)[Module.TREASURY] == ModuleStatus.DISABLED
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "module.configuration_changed")
    ).all()
    assert len(events) == 1
    assert events[0].payload == {"previous": None, "enabled": False, "revision": 1}
    assert verify_chain(db).ok
    bind_tenant(db, second.id)
    assert db.scalars(select(TenantModuleOverride)).all() == []
    assert effective_modules(db, second.id)[Module.TREASURY] == ModuleStatus.ENABLED
    with pytest.raises(ForbiddenError):
        configure(True, 1)
    db.add(
        TenantModuleOverride(
            tenant_id=first.id,
            module=Module.SALES.value,
            enabled=False,
            revision=1,
            updated_by_user_id=admin.id,
            updated_at=utcnow(),
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()
    db.rollback()
    bind_tenant(db, None)
    assert db.scalars(select(TenantModuleOverride)).all() == []
