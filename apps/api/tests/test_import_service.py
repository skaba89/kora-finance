from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.accounting.import_service import precheck_import_for_company
from kora.core.errors import ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.identity import CompanyMembership, User
from kora.models.ledger import JournalEntry
from kora.tenancy.roles import Role
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

HEADER = "journal;ecriture;date;compte;libelle;debit;credit\n"


def _csv(account: str = "571") -> bytes:
    return (
        HEADER + f"VT;1;2026-02-01;{account};Vente;10;0\nVT;1;2026-02-01;701;Vente;0;10\n"
    ).encode()


def test_precheck_uses_real_catalog_without_writing(db: Session, make_company: MakeCompany) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    report = precheck_import_for_company(
        user, company.id, _csv(), file_format="csv", source_currency="GNF"
    )
    assert report.valid
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_precheck_catalog_isolation(
    db: Session, client: TestClient, make_company: MakeCompany
) -> None:
    mine, other = make_company(), make_company()
    response = client.post(
        f"/api/v1/companies/{other.id}/accounts",
        headers=other.headers,
        json={"number": "552123456", "label": "Compte privé"},
    )
    assert response.status_code == 201
    user = db.get_one(User, mine.owner.id)
    report = precheck_import_for_company(
        user, mine.id, _csv("552123456"), file_format="csv", source_currency="GNF"
    )
    assert [(issue.row, issue.code) for issue in report.issues] == [(2, "unknown_account")]
    with pytest.raises(NotFoundError):
        precheck_import_for_company(
            user, other.id, _csv(), file_format="csv", source_currency="GNF"
        )


def test_precheck_requires_write_permission(
    db: Session, make_company: MakeCompany, make_user: MakeUser
) -> None:
    company = make_company()
    reader = make_user()
    db.add(CompanyMembership(company_id=company.id, user_id=reader.id, role=Role.PME_LECTEUR))
    db.commit()
    user = db.get_one(User, reader.id)
    with pytest.raises(ForbiddenError):
        precheck_import_for_company(
            user, company.id, _csv(), file_format="csv", source_currency="GNF"
        )


def test_precheck_rejects_currency_mismatch(db: Session, make_company: MakeCompany) -> None:
    company = make_company()
    user = db.get_one(User, company.owner.id)
    report = precheck_import_for_company(
        user, company.id, _csv(), file_format="csv", source_currency="EUR"
    )
    assert not report.valid
    assert report.issues[0].code == "currency_mismatch"
