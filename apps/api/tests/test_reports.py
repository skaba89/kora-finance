"""Balance générale et grand livre sur un jeu de référence calculé à la main."""

import random
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger, account_id

MakeCompany = Callable[..., CompanyFixture]


@pytest.fixture
def book(client: TestClient, make_company: MakeCompany) -> Ledger:
    """Exercice 2026 :
    1. AN 01/01 : banque 521 / capital 101 — 5 000 000
    2. VT 10/02 : client 411 1 180 000 / ventes 701 1 000 000 / TVA collectée 4431 180 000
    3. AC 05/03 : achats 601 400 000 + TVA déductible 4452 72 000 / fournisseur 401 472 000
    4. BQ 20/03 : banque 521 / client 411 — 1 180 000
    5. brouillon 25/03 (exclu de tous les états)
    """
    ledger = Ledger(client, make_company())
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    ledger.posted(
        [("411", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)],
        journal="VT",
        entry_date="2026-02-10",
    )
    ledger.posted(
        [("601", 400_000, 0), ("4452", 72_000, 0), ("401", 0, 472_000)],
        journal="AC",
        entry_date="2026-03-05",
    )
    ledger.posted(
        [("521", 1_180_000, 0), ("411", 0, 1_180_000)], journal="BQ", entry_date="2026-03-20"
    )
    draft = ledger.create([("601", 999, 0), ("401", 0, 999)], entry_date="2026-03-25")
    assert draft.status_code == 201
    return ledger


def _fiscal_year(ledger: Ledger) -> str:
    years = ledger.client.get(f"{ledger.base}/fiscal-years", headers=ledger.company.headers).json()
    return str(years[0]["id"])


def _balance(ledger: Ledger, **params: Any) -> Any:
    response = ledger.client.get(
        f"{ledger.base}/trial-balance",
        headers=ledger.company.headers,
        params={"fiscal_year_id": _fiscal_year(ledger), **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row(r: dict[str, str]) -> tuple[int, ...]:
    keys = (
        "opening_debit",
        "opening_credit",
        "period_debit",
        "period_credit",
        "closing_debit",
        "closing_credit",
    )
    return tuple(int(r[k]) for k in keys)


def test_balance_du_mois_de_mars(book: Ledger) -> None:
    result = _balance(book, date_from="2026-03-01", date_to="2026-03-31")
    rows = {r["number"]: _row(r) for r in result["rows"]}
    assert rows == {
        "101": (0, 5_000_000, 0, 0, 0, 5_000_000),
        "401": (0, 0, 0, 472_000, 0, 472_000),
        "411": (1_180_000, 0, 0, 1_180_000, 0, 0),
        "4431": (0, 180_000, 0, 0, 0, 180_000),
        "4452": (0, 0, 72_000, 0, 72_000, 0),
        "521": (5_000_000, 0, 1_180_000, 0, 6_180_000, 0),
        "601": (0, 0, 400_000, 0, 400_000, 0),
        "701": (0, 1_000_000, 0, 0, 0, 1_000_000),
    }
    assert _row(result["totals"]) == (
        6_180_000,
        6_180_000,
        1_652_000,
        1_652_000,
        6_652_000,
        6_652_000,
    )
    assert result["balanced"] is True
    # Montants en chaînes, comme partout dans l'API.
    assert result["totals"]["closing_debit"] == "6652000"


def test_les_a_nouveaux_sont_dans_l_ouverture_sur_l_exercice_entier(book: Ledger) -> None:
    rows = {r["number"]: _row(r) for r in _balance(book)["rows"]}
    assert rows["521"] == (5_000_000, 0, 1_180_000, 0, 6_180_000, 0)
    assert rows["411"] == (0, 0, 1_180_000, 1_180_000, 0, 0)


def test_le_brouillon_n_apparait_nulle_part(book: Ledger) -> None:
    rows = {r["number"]: _row(r) for r in _balance(book)["rows"]}
    assert rows["601"][2] == 400_000


def test_filtres_de_la_balance(book: Ledger) -> None:
    class4 = _balance(book, **{"class": 4})
    assert [r["number"] for r in class4["rows"]] == ["401", "411", "4431", "4452"]
    assert class4["balanced"] is None
    assert [r["number"] for r in _balance(book, prefix="44")["rows"]] == ["4431", "4452"]
    everything = _balance(book, include_zero="true")
    assert len(everything["rows"]) == 520
    assert everything["balanced"] is True


def test_periode_hors_exercice_refusee(book: Ledger) -> None:
    response = book.client.get(
        f"{book.base}/trial-balance",
        headers=book.company.headers,
        params={"fiscal_year_id": _fiscal_year(book), "date_from": "2025-12-01"},
    )
    assert response.status_code == 422


def test_exercice_d_un_autre_dossier(
    book: Ledger, client: TestClient, make_company: MakeCompany
) -> None:
    other = Ledger(client, make_company())
    response = client.get(
        f"{book.base}/trial-balance",
        headers=book.company.headers,
        params={"fiscal_year_id": _fiscal_year(other)},
    )
    assert response.status_code == 404


def _ledger(book: Ledger, number: str, **params: Any) -> Any:
    response = book.client.get(
        f"{book.base}/ledger",
        headers=book.company.headers,
        params={
            "fiscal_year_id": _fiscal_year(book),
            "account_id": account_id(book.client, book.base, book.company.headers, number),
            **params,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_grand_livre_banque_en_mars(book: Ledger) -> None:
    result = _ledger(book, "521", date_from="2026-03-01", date_to="2026-03-31")
    assert result["opening"] == "5000000"
    assert [
        (i["journal_code"], i["debit"], i["credit"], i["balance"]) for i in result["items"]
    ] == [("BQ", "1180000", "0", "6180000")]
    assert result["closing"] == "6180000"


def test_grand_livre_solde_crediteur_signe(book: Ledger) -> None:
    result = _ledger(book, "401")
    assert result["opening"] == "0"
    assert [i["balance"] for i in result["items"]] == ["-472000"]
    assert result["closing"] == "-472000"


def test_grand_livre_pagine_solde_exact_sur_chaque_page(book: Ledger) -> None:
    for day in range(1, 8):
        book.posted([("571", day * 1000, 0), ("701", 0, day * 1000)], entry_date=f"2026-04-0{day}")
    full = _ledger(book, "571")
    assert full["total"] == 7
    balances = [int(i["balance"]) for i in full["items"]]
    assert balances == [sum(range(1, n + 1)) * 1000 for n in range(1, 8)]
    page2 = _ledger(book, "571", limit=3, offset=3)
    assert [int(i["balance"]) for i in page2["items"]] == balances[3:6]
    assert page2["closing"] == full["closing"] == str(28_000)


def test_compte_d_un_autre_dossier(
    book: Ledger, client: TestClient, make_company: MakeCompany
) -> None:
    other = Ledger(client, make_company())
    response = client.get(
        f"{book.base}/ledger",
        headers=book.company.headers,
        params={
            "fiscal_year_id": _fiscal_year(book),
            "account_id": account_id(client, other.base, other.company.headers, "521"),
        },
    )
    assert response.status_code == 404


def test_balance_et_grand_livre_concordent_sur_des_donnees_aleatoires(
    client: TestClient, make_company: MakeCompany
) -> None:
    ledger = Ledger(client, make_company())
    rng = random.Random(2026)
    numbers = ["571", "521", "601", "701", "401", "411"]
    for _ in range(25):
        debit_account, credit_account = rng.sample(numbers, 2)
        amount = rng.randint(1, 10**9)
        month = rng.randint(1, 12)
        ledger.posted(
            [(debit_account, amount, 0), (credit_account, 0, amount)],
            entry_date=f"2026-{month:02d}-15",
        )
    result = _balance(ledger)
    assert result["balanced"] is True
    for row in result["rows"]:
        detail = _ledger(ledger, row["number"], limit=200)
        closing = int(row["closing_debit"]) - int(row["closing_credit"])
        assert int(detail["closing"]) == closing
        if detail["items"]:
            assert int(detail["items"][-1]["balance"]) == closing
