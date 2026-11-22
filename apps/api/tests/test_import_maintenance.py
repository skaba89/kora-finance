import uuid
from collections.abc import Callable

import pytest

from kora.accounting import import_purge
from kora.worker import tasks
from tests.conftest import CompanyFixture

MakeCompany = Callable[..., CompanyFixture]


def test_scan_enqueues_each_company(
    make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = make_company(), make_company()
    queued: list[str] = []
    monkeypatch.setattr(tasks.maintain_imports, "send", queued.append)
    tasks.scan_import_maintenance()
    assert {str(first.id), str(second.id)} <= set(queued)


def test_maintenance_chains_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    company_id = uuid.uuid4()
    expired: list[uuid.UUID] = []
    pages: list[tuple[uuid.UUID, str | None]] = []
    queued: list[tuple[str, str | None]] = []

    def purge(tenant_id: uuid.UUID) -> int:
        expired.append(tenant_id)
        return 1

    def page(tenant_id: uuid.UUID, *, cursor: str | None = None) -> tuple[int, str | None]:
        pages.append((tenant_id, cursor))
        return (1, "next") if cursor is None else (0, None)

    def enqueue(tenant_id: str, cursor: str | None = None) -> None:
        queued.append((tenant_id, cursor))

    monkeypatch.setattr(import_purge, "purge_expired_imports", purge)
    monkeypatch.setattr(import_purge, "purge_orphan_page", page)
    monkeypatch.setattr(tasks.reconcile_import_objects, "send", enqueue)
    tasks.maintain_imports(str(company_id))
    assert expired == [company_id]
    assert queued == [(str(company_id), None)]
    tasks.reconcile_import_objects(*queued.pop(0))
    assert queued == [(str(company_id), "next")]
    tasks.reconcile_import_objects(*queued.pop(0))
    assert pages == [(company_id, None), (company_id, "next")]
    assert not queued
