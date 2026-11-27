"""Rapport de précontrôle persisté : synthèse, anomalies paginées, isolation."""

import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting.import_service import MAX_PERSISTED_ISSUES
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import CompanyMembership
from kora.models.imports import ImportBatch, ImportBatchIssue
from kora.storage import objects
from kora.tenancy.roles import Role
from tests.conftest import CompanyFixture, UserFixture
from tests.test_import_service import HEADER

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

URL = "/api/v1/companies/{company_id}/accounting-imports"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}

    def put(key: str, sealed: objects.SealedObject) -> None:
        assert key not in blobs
        blobs[key] = sealed.blob

    def get(key: str, *, max_bytes: int | None = None) -> bytes:
        return blobs[key]

    monkeypatch.setattr(objects, "put", put)
    monkeypatch.setattr(objects, "get", get)
    monkeypatch.setattr(objects, "delete", lambda key: blobs.pop(key, None))
    return blobs


def _upload(client: TestClient, company: CompanyFixture, content: bytes) -> str:
    response = client.post(
        URL.format(company_id=company.id),
        params={"file_format": "csv", "source_currency": "GNF"},
        headers=company.headers,
        content=content,
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _precheck(client: TestClient, company: CompanyFixture, batch_id: str) -> dict[str, object]:
    response = client.post(
        f"{URL.format(company_id=company.id)}/{batch_id}/precheck", headers=company.headers
    )
    assert response.status_code == 200, response.text
    page: dict[str, object] = response.json()
    return page


def _csv_ecritures(count: int, *, journal: str = "XX") -> bytes:
    """Paires équilibrées d'un même journal (inconnu par défaut : 2 anomalies par paire).

    Le groupement d'écriture se fait par (journal, ecriture) : les deux lignes
    d'une paire doivent partager le même code, sinon chaque ligne reste isolée
    et ajoute une anomalie d'équilibre parasite au rapport attendu.
    """
    lines = [HEADER]
    for number in range(1, count + 1):
        lines.append(f"{journal};{number};2026-02-01;571;Vente;10;0\n")
        lines.append(f"{journal};{number};2026-02-01;701;Vente;0;10\n")
    return "".join(lines).encode()


def test_precheck_persists_summary(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(1, journal="VT"))
    report = _precheck(client, company, batch_id)
    assert report == {
        "rows": 2,
        "entries": 1,
        "debit": "10",
        "credit": "10",
        "valid": True,
        "issue_count": 0,
        "issues": [],
    }
    bind_tenant(db, company.id)
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    assert (batch.precheck_valid, batch.precheck_issue_count, batch.precheck_stored_issues) == (
        True,
        0,
        0,
    )
    assert (batch.precheck_rows, batch.precheck_entries) == (2, 1)
    assert db.scalar(select(func.count()).select_from(ImportBatchIssue)) == 0
    read = client.get(
        f"{URL.format(company_id=company.id)}/{batch_id}/precheck", headers=company.headers
    )
    assert read.status_code == 200, read.text
    page = read.json()
    assert (page["rows"], page["entries"], page["valid"]) == (2, 1, True)
    assert (page["issue_count"], page["stored_issues"], page["offset"], page["has_more"]) == (
        0,
        0,
        0,
        False,
    )
    assert page["issues"] == []


def test_precheck_persists_paginated_issues(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(7))
    report = _precheck(client, company, batch_id)
    assert report["issue_count"] == 14
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(ImportBatchIssue)) == 14
    base = f"{URL.format(company_id=company.id)}/{batch_id}/precheck"
    page = client.get(base, params={"limit": 3}, headers=company.headers).json()
    assert [(i["row"], i["code"]) for i in page["issues"]] == [
        (2, "unknown_journal"),
        (3, "unknown_journal"),
        (4, "unknown_journal"),
    ]
    assert (page["offset"], page["has_more"]) == (0, True)
    for offset in (3, 6, 9):
        page = client.get(
            base, params={"limit": 3, "offset": offset}, headers=company.headers
        ).json()
        assert [i["row"] for i in page["issues"]] == [offset + 2, offset + 3, offset + 4]
        assert (page["offset"], page["has_more"]) == (offset, True)
    last = client.get(base, params={"limit": 3, "offset": 12}, headers=company.headers).json()
    assert [i["row"] for i in last["issues"]] == [14, 15]
    assert (last["has_more"], last["stored_issues"], last["issue_count"]) == (False, 14, 14)
    beyond = client.get(base, params={"limit": 3, "offset": 15}, headers=company.headers).json()
    assert beyond["issues"] == []
    assert beyond["has_more"] is False


def test_reprecheck_replaces_persisted_issues(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(3))
    _precheck(client, company, batch_id)
    _precheck(client, company, batch_id)
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(ImportBatchIssue)) == 6
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    assert (batch.precheck_issue_count, batch.precheck_stored_issues) == (6, 6)


def test_persisted_issues_capped(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(MAX_PERSISTED_ISSUES // 2 + 200))
    report = _precheck(client, company, batch_id)
    total = 2 * (MAX_PERSISTED_ISSUES // 2 + 200)
    assert report["issue_count"] == total
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(ImportBatchIssue)) == MAX_PERSISTED_ISSUES
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    assert (batch.precheck_issue_count, batch.precheck_stored_issues) == (
        total,
        MAX_PERSISTED_ISSUES,
    )
    base = f"{URL.format(company_id=company.id)}/{batch_id}/precheck"
    page = client.get(
        base, params={"limit": 200, "offset": MAX_PERSISTED_ISSUES - 1}, headers=company.headers
    ).json()
    assert len(page["issues"]) == 1
    assert page["has_more"] is False


def test_read_report_isolated_and_authorized(
    db: Session,
    client: TestClient,
    make_company: MakeCompany,
    make_user: MakeUser,
    storage: dict[str, bytes],
) -> None:
    mine, other = make_company(), make_company()
    batch_id = _upload(client, mine, _csv_ecritures(1))
    _precheck(client, mine, batch_id)
    foreign = client.get(
        f"{URL.format(company_id=other.id)}/{batch_id}/precheck", headers=other.headers
    )
    assert foreign.status_code == 404
    reader = make_user()
    db.add(CompanyMembership(company_id=mine.id, user_id=reader.id, role=Role.PME_LECTEUR))
    db.commit()
    denied = client.get(
        f"{URL.format(company_id=mine.id)}/{batch_id}/precheck",
        headers=reader.headers(client),
    )
    assert denied.status_code == 403


def test_read_report_requires_prior_precheck(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(1))
    missing = client.get(
        f"{URL.format(company_id=company.id)}/{batch_id}/precheck", headers=company.headers
    )
    assert missing.status_code == 404
    bind_tenant(db, company.id)
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    batch.created_at = utcnow() - timedelta(days=2)
    batch.expires_at = utcnow() - timedelta(days=1)
    db.commit()
    expired = client.get(
        f"{URL.format(company_id=company.id)}/{batch_id}/precheck", headers=company.headers
    )
    assert expired.status_code == 404
    unknown = client.get(
        f"{URL.format(company_id=company.id)}/{uuid.uuid4()}/precheck", headers=company.headers
    )
    assert unknown.status_code == 404


def test_read_report_pagination_validation(
    client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_ecritures(1))
    base = f"{URL.format(company_id=company.id)}/{batch_id}/precheck"
    assert client.get(base, params={"limit": 0}, headers=company.headers).status_code == 422
    assert client.get(base, params={"limit": 201}, headers=company.headers).status_code == 422
    assert client.get(base, params={"offset": -1}, headers=company.headers).status_code == 422
