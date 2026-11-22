import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting import import_storage
from kora.accounting.import_purge import purge_expired_imports, purge_orphan_page
from kora.accounting.import_service import precheck_staged_import
from kora.accounting.import_storage import load_staged_content, read_staged_import, stage_import
from kora.api.v1 import imports as import_routes
from kora.core import quota
from kora.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
)
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import CompanyMembership, User
from kora.models.imports import ImportBatch
from kora.models.ledger import JournalEntry
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
    monkeypatch.setattr(objects, "delete", lambda key: blobs.pop(key, None))
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


def test_import_http_precheck(
    client: TestClient, make_company: MakeCompany, storage: dict[str, bytes], db: Session
) -> None:
    company, other = make_company(), make_company()
    url = f"/api/v1/companies/{company.id}/accounting-imports"
    content = (
        b"journal;ecriture;date;compte;libelle;debit;credit\n"
        b"VT;1;2026-02-01;571;Vente;10;0\nVT;1;2026-02-01;701;Vente;0;10\n"
    )
    response = client.post(
        url,
        params={"file_format": "csv", "source_currency": "GNF"},
        headers=company.headers,
        content=content,
    )
    assert response.status_code == 200, response.text
    batch = response.json()
    assert len(storage) == 1
    report = client.post(f"{url}/{batch['id']}/precheck", headers=company.headers)
    assert report.status_code == 200, report.text
    assert report.json() == {
        "rows": 2,
        "entries": 1,
        "debit": "10",
        "credit": "10",
        "valid": True,
        "issue_count": 0,
        "issues": [],
    }
    foreign_url = f"/api/v1/companies/{other.id}/accounting-imports/{batch['id']}/precheck"
    assert client.post(foreign_url, headers=other.headers).status_code == 404
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_import_http_size(
    client: TestClient, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = make_company()
    monkeypatch.setattr(import_routes, "MAX_UPLOAD_BYTES", 4)
    url = f"/api/v1/companies/{company.id}/accounting-imports"
    response = client.post(
        url,
        params={"file_format": "csv", "source_currency": "GNF"},
        headers=company.headers,
        content=b"12345",
    )
    assert response.status_code == 413


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


def test_purge_expired_preserves_active_and_other_tenants(
    db: Session, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    mine, other = make_company(), make_company()
    user = db.get_one(User, mine.owner.id)
    other_user = db.get_one(User, other.owner.id)
    expired = stage_import(user, mine.id, b"expired", file_format="csv", source_currency="GNF")
    active = stage_import(user, mine.id, b"active", file_format="csv", source_currency="GNF")
    unrelated = stage_import(
        other_user, other.id, b"expired", file_format="csv", source_currency="GNF"
    )
    for company_id, batch_id in ((mine.id, expired.id), (other.id, unrelated.id)):
        bind_tenant(db, company_id)
        batch = db.get_one(ImportBatch, batch_id)
        batch.created_at = utcnow() - timedelta(days=2)
        batch.expires_at = utcnow() - timedelta(days=1)
        db.commit()
    assert purge_expired_imports(mine.id) == 1
    assert purge_expired_imports(mine.id) == 0
    assert f"imports/{mine.id}/{expired.id}" not in storage
    assert f"imports/{other.id}/{unrelated.id}" in storage
    assert read_staged_import(user, mine.id, active.id) == b"active"
    replacement = stage_import(user, mine.id, b"expired", file_format="csv", source_currency="GNF")
    assert replacement.id != expired.id


def test_purge_storage_failure_is_retryable(
    db: Session,
    make_company: MakeCompany,
    storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    staged = stage_import(user, company.id, b"expired", file_format="csv", source_currency="GNF")
    bind_tenant(db, company.id)
    batch = db.get_one(ImportBatch, staged.id)
    batch.created_at = utcnow() - timedelta(days=2)
    batch.expires_at = utcnow() - timedelta(days=1)
    db.commit()

    def fail(key: str) -> None:
        raise ServiceUnavailableError("Stockage indisponible.")

    with monkeypatch.context() as patch:
        patch.setattr(objects, "delete", fail)
        with pytest.raises(ServiceUnavailableError):
            purge_expired_imports(company.id)
    assert f"imports/{company.id}/{staged.id}" in storage
    assert purge_expired_imports(company.id) == 1


def test_orphan_reconciliation_preserves_references_and_recent_objects(
    db: Session,
    make_company: MakeCompany,
    storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    active = stage_import(user, company.id, b"active", file_format="csv", source_currency="GNF")
    prefix = f"imports/{company.id}/"
    valid = f"{prefix}{active.id}"
    orphan = f"{prefix}{uuid.uuid4()}"
    recent = f"{prefix}{uuid.uuid4()}"
    foreign = f"imports/{uuid.uuid4()}/{uuid.uuid4()}"
    malformed = f"{prefix}not-a-uuid"
    old = utcnow() - timedelta(days=3)
    for key in (orphan, recent, foreign, malformed):
        storage[key] = b"encrypted"

    def page(
        requested: str, *, cursor: str | None = None
    ) -> tuple[list[tuple[str, datetime]], str | None]:
        assert requested == prefix
        if cursor is None:
            return [(valid, old), (orphan, old), (recent, utcnow())], "next"
        assert cursor == "next"
        return [(foreign, old), (malformed, old)], None

    monkeypatch.setattr(objects, "list_page", page)
    assert purge_orphan_page(company.id) == (1, "next")
    assert purge_orphan_page(company.id, cursor="next") == (0, None)
    assert orphan not in storage
    assert {valid, recent, foreign, malformed} <= storage.keys()
    assert read_staged_import(user, company.id, active.id) == b"active"


def test_precheck_staged_uses_persisted_options_and_catalog(
    db: Session, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    content = (
        b"journal;ecriture;date;compte;libelle;debit;credit\n"
        b"VT;1;2026-02-01;571;Vente;10;0\nVT;1;2026-02-01;701;Vente;0;10\n"
    )
    staged = stage_import(user, company.id, content, file_format="csv", source_currency="GNF")
    report = precheck_staged_import(user, company.id, staged.id)
    assert report.valid
    assert (report.rows, report.entries, report.debit, report.credit) == (2, 1, 10, 10)
    wrong_format = stage_import(
        user, company.id, content, file_format="fec", source_currency="GNF", fec_delimiter="\t"
    )
    loaded = load_staged_content(user, company.id, wrong_format.id)
    assert (loaded.file_format, loaded.currency, loaded.fec_delimiter) == ("fec", "GNF", "\t")
    assert not precheck_staged_import(user, company.id, wrong_format.id).valid
    assert len(storage) == 2
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_stage_capacity_preserves_replay_and_isolates_tenants(
    db: Session,
    make_company: MakeCompany,
    storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine, other = make_company(), make_company()
    user = db.get_one(User, mine.owner.id)
    other_user = db.get_one(User, other.owner.id)
    monkeypatch.setattr(import_storage, "MAX_STAGED_FILES", 1)
    first = stage_import(user, mine.id, b"one", file_format="csv", source_currency="GNF")
    assert stage_import(user, mine.id, b"one", file_format="csv", source_currency="GNF") == first
    with pytest.raises(ConflictError):
        stage_import(user, mine.id, b"two", file_format="csv", source_currency="GNF")
    monkeypatch.setattr(import_storage, "MAX_STAGED_BYTES", 2)
    with pytest.raises(ConflictError):
        stage_import(other_user, other.id, b"one", file_format="csv", source_currency="GNF")
    stage_import(other_user, other.id, b"ok", file_format="csv", source_currency="GNF")
    assert len(storage) == 2


def test_import_quota_fails_closed(
    db: Session, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    monkeypatch.setattr(quota, "allowed", lambda *args, **kwargs: False)
    with pytest.raises(TooManyRequestsError):
        stage_import(user, company.id, b"data", file_format="csv", source_currency="GNF")

    def fail(scope: str, subject: str, *, limit: int, window_seconds: int) -> bool:
        raise RedisError("Redis indisponible")

    monkeypatch.setattr(quota, "allowed", fail)
    with pytest.raises(ServiceUnavailableError):
        stage_import(user, company.id, b"data", file_format="csv", source_currency="GNF")
