import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from kora.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant, current_tenant
from kora.models.identity import User
from kora.tenancy.access import resolve_role
from kora.tenancy.module_admin import bind_module_client, list_module_clients
from kora.tenancy.module_config import module_configuration, set_module_override
from kora.tenancy.modules import Module, ModuleStatus
from tests.conftest import CompanyFixture, UserFixture


def test_administration_modules_sans_acces_comptable(
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
) -> None:
    first = make_company()
    second = make_company()
    admin = make_user()
    user = db.get_one(User, admin.id)
    user.is_platform_admin = True
    db.commit()
    with pytest.raises(ForbiddenError):
        list_module_clients(db, first.owner.id)
    with pytest.raises(ForbiddenError):
        bind_module_client(db, first.owner.id, first.id)
    with pytest.raises(BusinessRuleError):
        list_module_clients(db, admin.id, limit=201)
    with pytest.raises(NotFoundError):
        bind_module_client(db, admin.id, uuid.uuid4())
    assert current_tenant(db) is None
    page = list_module_clients(db, admin.id, limit=1)
    assert page.total >= 2
    assert len(page.items) == 1
    assert list_module_clients(db, admin.id, limit=1, offset=1).items != page.items
    assert resolve_role(db, user, first.id) is None
    bind_module_client(db, admin.id, first.id)
    with pytest.raises(ForbiddenError):
        bind_module_client(db, admin.id, second.id)
    with pytest.raises(ForbiddenError):
        list_module_clients(db, admin.id)
    initial = {row.module: row for row in module_configuration(db, first.id)}
    assert set(initial) == set(Module)
    assert initial[Module.TREASURY].revision == 0
    assert initial[Module.TREASURY].configured_enabled is None
    assert initial[Module.OCR].configured_status == ModuleStatus.UNRELEASED
    set_module_override(
        db,
        first.id,
        actor_id=admin.id,
        module=Module.TREASURY,
        enabled=False,
        expected_revision=0,
    )
    db.commit()
    changed = {row.module: row for row in module_configuration(db, first.id)}
    assert changed[Module.TREASURY].configured_enabled is False
    assert changed[Module.TREASURY].revision == 1
    assert changed[Module.FORECAST].configured_status == ModuleStatus.DEPENDENCY_DISABLED
    assert changed[Module.FORECAST].configured_enabled is None
    assert changed[Module.FORECAST].dependencies == (Module.TREASURY,)
    bind_tenant(db, None)
    bind_module_client(db, admin.id, second.id)
    assert module_configuration(db, second.id) == list(initial.values())
    bind_tenant(db, None)
    user.is_platform_admin = False
    db.commit()
    with pytest.raises(ForbiddenError):
        list_module_clients(db, admin.id)
    with pytest.raises(ForbiddenError):
        bind_module_client(db, admin.id, first.id)
