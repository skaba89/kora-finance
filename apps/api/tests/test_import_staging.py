import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.imports import ImportBatch
from tests.conftest import CompanyFixture

MakeCompany = Callable[..., CompanyFixture]


def _batch(company: CompanyFixture, **overrides: object) -> ImportBatch:
    batch_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": batch_id,
        "tenant_id": company.id,
        "uploaded_by_user_id": company.owner.id,
        "format": "csv",
        "currency": "GNF",
        "delimiter": "NONE",
        "size_bytes": 100,
        "sha256": "a" * 64,
        "storage_key": f"imports/{company.id}/{batch_id}",
        "wrapped_key": b"encrypted-key-fixture",
        "expires_at": utcnow() + timedelta(hours=24),
    }
    fields.update(overrides)
    return ImportBatch(**fields)


def test_staging_metadata_isolated_by_tenant(db: Session, make_company: MakeCompany) -> None:
    mine, other = make_company(), make_company()
    bind_tenant(db, mine.id)
    batch = _batch(mine)
    db.add(batch)
    db.commit()
    batch_id = batch.id
    bind_tenant(db, other.id)
    assert db.scalar(select(ImportBatch.id).where(ImportBatch.id == batch_id)) is None
    db.add(_batch(other))  # Même empreinte autorisée dans un autre dossier.
    db.commit()
    bind_tenant(db, None)
    assert db.scalar(select(ImportBatch.id).where(ImportBatch.id == batch_id)) is None
    with pytest.raises(DBAPIError):
        db.add(_batch(mine, sha256="b" * 64))
        db.flush()
    db.rollback()


def test_staging_prevents_duplicate_file_options(db: Session, make_company: MakeCompany) -> None:
    company = make_company()
    bind_tenant(db, company.id)
    db.add(_batch(company))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(_batch(company))
        db.flush()
    db.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"size_bytes": 0},
        {"size_bytes": 33554433},
        {"format": "xlsx", "size_bytes": 16777217},
        {"format": "fec", "delimiter": "NONE"},
        {"currency": "EUR"},
        {"sha256": "invalid"},
        {"wrapped_key": b""},
        {"storage_key": "imports/other"},
    ],
)
def test_staging_constraints(
    db: Session, make_company: MakeCompany, overrides: dict[str, object]
) -> None:
    company = make_company()
    bind_tenant(db, company.id)
    with pytest.raises(IntegrityError):
        db.add(_batch(company, **overrides))
        db.flush()
    db.rollback()
