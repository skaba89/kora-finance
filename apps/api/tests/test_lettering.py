"""Lettrage des comptes de tiers."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kora.accounting.lettering import lettering_code
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger, account_id

MakeCompany = Callable[..., CompanyFixture]


@pytest.mark.parametrize(
    ("sequence", "code"), [(1, "A"), (26, "Z"), (27, "AA"), (702, "ZZ"), (703, "AAA")]
)
def test_codes_de_lettrage(sequence: int, code: str) -> None:
    assert lettering_code(sequence) == code


@pytest.fixture
def book(client: TestClient, make_company: MakeCompany) -> Ledger:
    """Facture F-001 de 1 180 000 réglée en deux fois (500 000 puis 680 000)."""
    ledger = Ledger(client, make_company())
    ledger.posted(
        [("411", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)],
        journal="VT",
        entry_date="2026-02-10",
    )
    for amount, day in ((500_000, "2026-03-01"), (680_000, "2026-03-20")):
        ledger.posted([("521", amount, 0), ("411", 0, amount)], journal="BQ", entry_date=day)
    return ledger


def _lines(book: Ledger, number: str = "411", status: str = "open") -> Any:
    response = book.client.get(
        f"{book.base}/lettering/lines",
        headers=book.company.headers,
        params={
            "account_id": account_id(book.client, book.base, book.company.headers, number),
            "status": status,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _letter(book: Ledger, line_ids: list[str], number: str = "411") -> Any:
    return book.client.post(
        f"{book.base}/letterings",
        headers=book.company.headers,
        json={
            "account_id": account_id(book.client, book.base, book.company.headers, number),
            "line_ids": line_ids,
        },
    )


def test_lettrage_d_une_facture_reglee_en_deux_fois(book: Ledger) -> None:
    open_lines = _lines(book)
    assert open_lines["total"] == 3
    assert open_lines["open_balance"] == "0"
    ids = [line["line_id"] for line in open_lines["items"]]

    partial = _letter(book, ids[:2])
    assert partial.status_code == 422
    assert "écart 680000" in partial.json()["errors"][0]

    created = _letter(book, ids)
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "A"
    assert _lines(book)["total"] == 0
    lettered = _lines(book, status="lettered")["items"]
    assert {line["lettering_code"] for line in lettered} == {"A"}

    again = _letter(book, ids)
    assert again.status_code == 422
    assert "déjà lettrée" in again.json()["errors"][0]

    deleted = book.client.delete(
        f"{book.base}/letterings/{created.json()['id']}", headers=book.company.headers
    )
    assert deleted.status_code == 204
    assert _lines(book)["total"] == 3


def test_solde_non_lettre(book: Ledger) -> None:
    book.posted([("411", 300_000, 0), ("701", 0, 300_000)], journal="VT", entry_date="2026-04-01")
    lines = _lines(book)
    first_three = [line["line_id"] for line in lines["items"][:3]]
    _letter(book, first_three)
    remaining = _lines(book)
    assert remaining["open_balance"] == "300000"
    assert remaining["total"] == 1


def test_codes_successifs(book: Ledger) -> None:
    ids = [line["line_id"] for line in _lines(book)["items"]]
    assert _letter(book, ids).json()["code"] == "A"
    book.posted([("411", 50_000, 0), ("701", 0, 50_000)], journal="VT", entry_date="2026-05-01")
    book.posted([("521", 50_000, 0), ("411", 0, 50_000)], journal="BQ", entry_date="2026-05-02")
    second = [line["line_id"] for line in _lines(book)["items"]]
    assert _letter(book, second).json()["code"] == "B"


def test_lettrage_automatique_par_reference(client: TestClient, make_company: MakeCompany) -> None:
    ledger = Ledger(client, make_company())
    headers = ledger.company.headers
    references = ["F-1", "f-1 ", "F-2", "F-2"]
    bodies = [
        ledger.body([("411", 1_000, 0), ("701", 0, 1_000)], journal="VT", entry_date="2026-02-01"),
        ledger.body([("521", 1_000, 0), ("411", 0, 1_000)], journal="BQ", entry_date="2026-02-05"),
        ledger.body([("411", 2_000, 0), ("701", 0, 2_000)], journal="VT", entry_date="2026-02-02"),
        ledger.body([("521", 1_500, 0), ("411", 0, 1_500)], journal="BQ", entry_date="2026-02-06"),
    ]
    for body, reference in zip(bodies, references, strict=True):
        created = client.post(
            f"{ledger.base}/entries", headers=headers, json={**body, "reference": reference}
        )
        assert ledger.post(created.json()["id"]).status_code == 200
    response = client.post(
        f"{ledger.base}/letterings/auto",
        headers=headers,
        json={"account_id": account_id(client, ledger.base, headers, "411")},
    )
    assert response.json() == {"created": 1}
    # F-1 lettrée (référence comparée sans tenir compte de la casse ni des espaces) ;
    # F-2 partiellement réglée : laissée au lettrage manuel.
    assert _lines(ledger)["open_balance"] == "500"
    assert _lines(ledger)["total"] == 2


def test_compte_non_lettrable(book: Ledger) -> None:
    response = book.client.get(
        f"{book.base}/lettering/lines",
        headers=book.company.headers,
        params={"account_id": account_id(book.client, book.base, book.company.headers, "521")},
    )
    assert response.status_code == 422
    assert "classe 4" in response.json()["detail"]


def test_ligne_de_brouillon_ou_inconnue(book: Ledger) -> None:
    ids = [line["line_id"] for line in _lines(book)["items"]]
    assert book.create([("411", 10, 0), ("701", 0, 10)]).status_code == 201
    # Ligne de brouillon : jamais proposée au lettrage.
    assert _lines(book)["total"] == 3
    response = _letter(book, [ids[0], "00000000-0000-4000-8000-000000000000"])
    assert response.status_code == 422
    assert "introuvable" in response.json()["detail"]


def test_ligne_d_un_autre_compte(book: Ledger) -> None:
    receivable = [line["line_id"] for line in _lines(book)["items"]]
    supplier = book.posted([("601", 5, 0), ("401", 0, 5)], journal="AC")
    assert supplier["status"] == "POSTED"
    payable = [line["line_id"] for line in _lines(book, "401")["items"]]
    response = _letter(book, [*receivable, *payable])
    assert response.status_code == 422
    assert "compte 411" in response.json()["errors"][0]


def test_idor_lettrage_d_un_autre_dossier(
    book: Ledger, client: TestClient, make_company: MakeCompany
) -> None:
    theirs = Ledger(client, make_company())
    theirs.posted([("411", 7, 0), ("701", 0, 7)], journal="VT")
    theirs.posted([("521", 7, 0), ("411", 0, 7)], journal="BQ")
    their_ids = [line["line_id"] for line in _lines(theirs)["items"]]
    their_lettering = _letter(theirs, their_ids).json()["id"]

    # Lignes d'un autre dossier depuis son propre dossier : introuvables.
    response = _letter(book, their_ids)
    assert response.status_code == 422
    assert "introuvable" in response.json()["detail"]
    deleted = client.delete(
        f"{book.base}/letterings/{their_lettering}", headers=book.company.headers
    )
    assert deleted.status_code == 404


def test_la_base_refuse_un_lettrage_desequilibre(book: Ledger) -> None:
    ids = [line["line_id"] for line in _lines(book)["items"]]
    lettering = _letter(book, ids).json()["id"]
    with get_sessionmaker()() as session:
        bind_tenant(session, book.company.id)
        session.execute(
            text("DELETE FROM lettering_lines WHERE lettering_id = :l AND line_id = :line"),
            {"l": lettering, "line": ids[0]},
        )
        with pytest.raises(DBAPIError, match="invalide"):
            session.commit()


def test_la_base_refuse_un_lettrage_sur_un_autre_compte(book: Ledger) -> None:
    ids = [line["line_id"] for line in _lines(book)["items"]]
    with get_sessionmaker()() as session:
        bind_tenant(session, book.company.id)
        account_401 = session.execute(
            text("SELECT id FROM accounts WHERE tenant_id = :t AND number = '401'"),
            {"t": book.company.id},
        ).scalar_one()
        lettering = session.execute(
            text(
                "INSERT INTO letterings (id, tenant_id, account_id, sequence, created_by_user_id) "
                "VALUES (gen_random_uuid(), :t, :a, 99, :u) RETURNING id"
            ),
            {"t": book.company.id, "a": account_401, "u": book.company.owner.id},
        ).scalar_one()
        for line_id in ids:
            session.execute(
                text(
                    "INSERT INTO lettering_lines (tenant_id, lettering_id, line_id) "
                    "VALUES (:t, :l, :i)"
                ),
                {"t": book.company.id, "l": lettering, "i": line_id},
            )
        with pytest.raises(DBAPIError, match="lignes étrangères"):
            session.commit()


def test_audit_du_lettrage(book: Ledger) -> None:
    ids = [line["line_id"] for line in _lines(book)["items"]]
    _letter(book, ids)
    events = book.client.get(f"{book.base}/audit-events", headers=book.company.headers).json()[
        "items"
    ]
    event = next(e for e in events if e["action"] == "lettering.created")
    assert event["payload"]["compte"] == "411"
    assert event["payload"]["code"] == "A"
