from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting.import_storage import read_staged_import, stage_import
from kora.core.errors import ConflictError, ForbiddenError, NotFoundError, ServiceUnavailableError
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import CompanyMembership, User
from kora.models.imports import ImportBatch
from kora.storage import objects
from kora.tenancy.roles import Role
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}

    def put(key: str, sealed: objects.SealedObject) -> None:
        assert key not in blobs
        blobs[key] = sealed.blob

    def get(key: str, *, max_bytes: int | None = None) -> bytes:
        blob = blobs[key]
        if max_bytes is not None and len(blob) > max_bytes:
            raise objects.CorruptedObjectError(key)
        return blob

    monkeypatch.setattr(objects, "put", put)
    monkeypatch.setattr(objects, "get", get)
    return blobs


def test_stage_replay_and_integrity(
    db: Session, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    content = b"confidential accounting data"
    first = stage_import(user, company.id, content, file_format="csv", source_currency="GNF")
    replay = stage_import(user, company.id, content, file_format="csv", source_currency="GNF")
    assert replay == first
    assert read_staged_import(user, company.id, first.id) == content
    key = f"imports/{company.id}/{first.id}"
    assert len(storage) == 1
    assert content not in storage[key]
    storage[key] = storage[key][:-1] + bytes([storage[key][-1] ^ 1])
    with pytest.raises(ServiceUnavailableError):
        read_staged_import(user, company.id, first.id)


def test_stage_access_and_expiration(
    db: Session, make_company: MakeCompany, make_user: MakeUser, storage: dict[str, bytes]
) -> None:
    mine, other = make_company(), make_company()
    user = db.get_one(User, mine.owner.id)
    first = stage_import(user, mine.id, b"data", file_format="csv", source_currency="GNF")
    with pytest.raises(NotFoundError):
        read_staged_import(user, other.id, first.id)
    reader = make_user()
    db.add(CompanyMembership(company_id=mine.id, user_id=reader.id, role=Role.PME_LECTEUR))
    db.commit()
    with pytest.raises(ForbiddenError):
        read_staged_import(db.get_one(User, reader.id), mine.id, first.id)
    bind_tenant(db, mine.id)
    batch = db.get_one(ImportBatch, first.id)
    batch.created_at = utcnow() - timedelta(days=2)
    batch.expires_at = utcnow() - timedelta(days=1)
    db.commit()
    with pytest.raises(NotFoundError):
        read_staged_import(user, mine.id, first.id)
    with pytest.raises(ConflictError):
        stage_import(user, mine.id, b"data", file_format="csv", source_currency="GNF")
    assert len(storage) == 1


def test_failed_upload_rolls_back(
    db: Session, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)

    def fail(key: str, sealed: objects.SealedObject) -> None:
        raise ServiceUnavailableError("Stockage indisponible.")

    monkeypatch.setattr(objects, "put", fail)
    with pytest.raises(ServiceUnavailableError):
        stage_import(user, company.id, b"data", file_format="csv", source_currency="GNF")
    bind_tenant(db, company.id)
    assert db.scalar(select(ImportBatch.id)) is None
