"""Verrouillage de période, clôture, à-nouveaux et réouverture."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import Ledger, account_id

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


def _years(book: Ledger) -> dict[str, dict[str, Any]]:
    years = book.client.get(f"{book.base}/fiscal-years", headers=book.company.headers).json()
    return {y["start_date"][:4]: y for y in years}


def _add_year(book: Ledger, year: int) -> None:
    response = book.client.post(
        f"{book.base}/fiscal-years",
        headers=book.company.headers,
        json={"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
    )
    assert response.status_code == 201, response.text


def _fy_url(book: Ledger, year: str, action: str) -> str:
    return f"{book.base}/fiscal-years/{_years(book)[year]['id']}/{action}"


def _balance(book: Ledger, year: str) -> dict[str, int]:
    """Solde de clôture signé (positif = débiteur) par compte, et ouverture en « ouv:… »."""
    result = book.client.get(
        f"{book.base}/trial-balance",
        headers=book.company.headers,
        params={"fiscal_year_id": _years(book)[year]["id"]},
    ).json()
    balances: dict[str, int] = {}
    for row in result["rows"]:
        balances[row["number"]] = int(row["closing_debit"]) - int(row["closing_credit"])
        balances[f"ouv:{row['number']}"] = int(row["opening_debit"]) - int(row["opening_credit"])
    return balances


@pytest.fixture
def book(client: TestClient, make_company: MakeCompany) -> Ledger:
    """2026 : apport 5 000 000, vente 1 000 000 HT (+ TVA 180 000) encaissée, achat
    400 000 non réglé. Résultat attendu : bénéfice de 600 000."""
    ledger = Ledger(client, make_company())
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    ledger.posted(
        [("411", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)],
        journal="VT",
        entry_date="2026-02-10",
    )
    ledger.posted([("601", 400_000, 0), ("401", 0, 400_000)], journal="AC", entry_date="2026-03-05")
    ledger.posted(
        [("521", 1_180_000, 0), ("411", 0, 1_180_000)], journal="BQ", entry_date="2026-03-20"
    )
    return ledger


# --- Verrouillage


def test_periode_verrouillee(book: Ledger) -> None:
    locked = book.client.post(
        _fy_url(book, "2026", "lock"),
        headers=book.company.headers,
        json={"locked_until": "2026-03-31"},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["locked_until"] == "2026-03-31"
    refused = book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-03-31")
    assert refused.status_code == 422
    assert "verrouillée jusqu'au 31/03/2026" in refused.json()["detail"]
    assert book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-04-01").status_code == 201
    posted = book.posted([("571", 5, 0), ("701", 0, 5)], entry_date="2026-04-02")
    reversal = book.client.post(
        f"{book.base}/entries/{posted['id']}/reversal",
        headers=book.company.headers,
        json={"entry_date": "2026-03-01"},
    )
    assert reversal.status_code == 422


def test_verrouillage_refuse_avec_brouillons(book: Ledger) -> None:
    assert book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-02-01").status_code == 201
    response = book.client.post(
        _fy_url(book, "2026", "lock"),
        headers=book.company.headers,
        json={"locked_until": "2026-03-31"},
    )
    assert response.status_code == 422
    assert "1 brouillon" in response.json()["detail"]


def test_seul_le_dirigeant_deverrouille(
    book: Ledger, client: TestClient, make_user: MakeUser
) -> None:
    accountant = make_user()
    client.post(
        f"{book.base}/members",
        headers=book.company.headers,
        json={"email": accountant.email, "role": "PME_COMPTABLE"},
    )
    headers = accountant.headers(client)
    url = _fy_url(book, "2026", "lock")
    assert client.post(url, headers=headers, json={"locked_until": "2026-03-31"}).status_code == 200
    unlock = client.post(url, headers=headers, json={"locked_until": None})
    assert unlock.status_code == 422
    assert (
        client.post(url, headers=book.company.headers, json={"locked_until": None}).status_code
        == 200
    )


def test_la_base_refuse_une_ecriture_dans_une_periode_verrouillee(book: Ledger) -> None:
    draft = book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-06-01").json()
    book.client.post(
        _fy_url(book, "2026", "lock"),
        headers=book.company.headers,
        json={"locked_until": "2026-05-31"},
    )
    with get_sessionmaker()() as session:
        bind_tenant(session, book.company.id)
        with pytest.raises(DBAPIError, match="Période verrouillée"):
            session.execute(
                text("UPDATE journal_entries SET entry_date = '2026-05-15' WHERE id = :id"),
                {"id": draft["id"]},
            )


# --- Clôture


def test_controle_prealable(book: Ledger) -> None:
    check = book.client.get(
        _fy_url(book, "2026", "closing-check"), headers=book.company.headers
    ).json()
    assert check["ready"] is False
    assert any("exercice suivant" in issue for issue in check["issues"])
    assert check["result"] == "600000"
    _add_year(book, 2027)
    book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-12-01")
    check = book.client.get(
        _fy_url(book, "2026", "closing-check"), headers=book.company.headers
    ).json()
    assert check["issues"] == ["1 brouillon(s) à valider ou supprimer."]
    refused = book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    assert refused.status_code == 422
    assert refused.json()["errors"] == check["issues"]


def test_les_a_nouveaux_reproduisent_exactement_le_bilan_de_cloture(book: Ledger) -> None:
    _add_year(book, 2027)
    closed = book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["fiscal_year"]["status"] == "CLOSED"

    before = _balance(book, "2026")
    after = _balance(book, "2027")
    sheet = {n: v for n, v in before.items() if not n.startswith("ouv:") and n[0] in "12345"}
    carried = {n: v for n, v in sheet.items() if v}
    assert carried  # le jeu de données a bien des soldes de bilan
    assert {n: after[f"ouv:{n}"] for n in carried} == carried
    assert after["ouv:131"] == -600_000  # bénéfice : solde créditeur
    assert not any(n[0] in "678" for n in after if not n.startswith("ouv:"))

    entry = book.client.get(
        f"{book.base}/entries/{closed.json()['opening_entry_id']}", headers=book.company.headers
    ).json()
    assert (entry["journal_code"], entry["entry_date"], entry["status"]) == (
        "AN",
        "2027-01-01",
        "POSTED",
    )
    assert entry["total_debit"] == entry["total_credit"] == "6180000"


def test_perte_reportee_au_compte_139(client: TestClient, make_company: MakeCompany) -> None:
    ledger = Ledger(client, make_company())
    ledger.posted([("601", 250_000, 0), ("521", 0, 250_000)], journal="BQ", entry_date="2026-05-01")
    _add_year(ledger, 2027)
    assert (
        ledger.client.post(
            _fy_url(ledger, "2026", "closing"), headers=ledger.company.headers
        ).status_code
        == 200
    )
    after = _balance(ledger, "2027")
    assert after["ouv:139"] == 250_000
    assert after["ouv:521"] == -250_000


def test_exercice_cloture_fige(book: Ledger) -> None:
    _add_year(book, 2027)
    book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    refused = book.create([("571", 10, 0), ("701", 0, 10)], entry_date="2026-12-01")
    assert refused.status_code == 422
    assert "clôturé" in refused.json()["detail"]
    lock = book.client.post(
        _fy_url(book, "2026", "lock"), headers=book.company.headers, json={"locked_until": None}
    )
    assert lock.status_code == 422


def test_lettrage_par_dela_la_cloture(book: Ledger) -> None:
    """Le fournisseur reste lettrable avec sa facture d'origine ; les à-nouveaux générés
    ne sont pas proposés (sinon le solde serait compté deux fois)."""
    _add_year(book, 2027)
    book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    params = {"account_id": account_id(book.client, book.base, book.company.headers, "401")}
    lines = book.client.get(
        f"{book.base}/lettering/lines", headers=book.company.headers, params=params
    ).json()
    assert lines["open_balance"] == "-400000"
    assert len(lines["items"]) == 1
    book.posted([("401", 400_000, 0), ("521", 0, 400_000)], journal="BQ", entry_date="2027-02-01")
    lines = book.client.get(
        f"{book.base}/lettering/lines", headers=book.company.headers, params=params
    ).json()
    created = book.client.post(
        f"{book.base}/letterings",
        headers=book.company.headers,
        json={**params, "line_ids": [line["line_id"] for line in lines["items"]]},
    )
    assert created.status_code == 201, created.text


def test_reouverture_puis_nouvelle_cloture(book: Ledger) -> None:
    _add_year(book, 2027)
    first = book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers).json()
    reopened = book.client.post(_fy_url(book, "2026", "reopening"), headers=book.company.headers)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "OPEN"
    # À-nouveaux contre-passés : plus rien en ouverture de 2027.
    assert all(v == 0 for n, v in _balance(book, "2027").items())
    original = book.client.get(
        f"{book.base}/entries/{first['opening_entry_id']}", headers=book.company.headers
    ).json()
    assert original["reversed_by_id"] is not None

    # Correction dans 2026, puis nouvelle clôture : les à-nouveaux suivent.
    book.posted([("601", 100_000, 0), ("521", 0, 100_000)], journal="BQ", entry_date="2026-12-15")
    again = book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    assert again.status_code == 200, again.text
    after = _balance(book, "2027")
    assert after["ouv:131"] == -500_000
    assert after["ouv:521"] == 6_080_000


def test_reouverture_impossible_si_l_exercice_suivant_est_cloture(book: Ledger) -> None:
    _add_year(book, 2027)
    _add_year(book, 2028)
    assert (
        book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers).status_code
        == 200
    )
    assert (
        book.client.post(_fy_url(book, "2027", "closing"), headers=book.company.headers).status_code
        == 200
    )
    refused = book.client.post(_fy_url(book, "2026", "reopening"), headers=book.company.headers)
    assert refused.status_code == 422
    assert "exercice suivant est clôturé" in refused.json()["detail"]


def test_le_comptable_ne_cloture_pas(book: Ledger, client: TestClient, make_user: MakeUser) -> None:
    accountant = make_user()
    client.post(
        f"{book.base}/members",
        headers=book.company.headers,
        json={"email": accountant.email, "role": "PME_COMPTABLE"},
    )
    _add_year(book, 2027)
    response = client.post(_fy_url(book, "2026", "closing"), headers=accountant.headers(client))
    assert response.status_code == 403


def test_audit_de_la_cloture(book: Ledger) -> None:
    _add_year(book, 2027)
    book.client.post(_fy_url(book, "2026", "closing"), headers=book.company.headers)
    events = book.client.get(f"{book.base}/audit-events", headers=book.company.headers).json()[
        "items"
    ]
    event = next(e for e in events if e["action"] == "fiscal_year.closed")
    assert event["payload"]["resultat"] == 600_000
