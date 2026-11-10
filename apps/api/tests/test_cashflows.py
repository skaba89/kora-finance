"""Tableau des flux de trésorerie (TFT), méthode directe."""

import random
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kora.accounting import cashflows
from kora.accounting.setup import reference_chart
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]


# --- Référentiel


def test_chaque_compte_hors_tresorerie_est_affecte_au_tft() -> None:
    by_code = {line.code: line for line in cashflows.template()}
    for number, _ in reference_chart():
        if number.startswith("5"):
            continue  # la classe 5 EST la trésorerie : jamais une contrepartie
        mapping = cashflows.mapping_for(number)
        assert mapping is not None, f"compte {number} sans affectation TFT"
        for target in (mapping.if_debit, mapping.if_credit):
            assert by_code[target.code].kind == "ligne", (number, target.code)


def test_les_totaux_du_tft_couvre_chaque_ligne_une_fois() -> None:
    lines = cashflows.template()
    lignes = {line.code for line in lines if line.kind == "ligne"}

    def expand(code: str) -> Counter[str]:
        line = {line.code: line for line in lines}[code]
        if line.kind != "total":
            return Counter({code: 1})
        result: Counter[str] = Counter()
        for _, part in line.formula:
            for leaf, coefficient in expand(part).items():
                result[leaf] += coefficient
        return result

    counter = expand("XV")
    assert {c: v for c, v in counter.items() if v} == dict.fromkeys(lignes, 1)


def test_la_classe_5_n_est_jamais_une_affectation() -> None:
    for mapping in cashflows.mappings():
        assert not mapping.prefix.startswith("5"), mapping.prefix


# --- Calcul sur un jeu de référence


def _fy(book: Ledger, year: str) -> str:
    years = book.client.get(f"{book.base}/fiscal-years", headers=book.company.headers).json()
    return str(next(y["id"] for y in years if y["start_date"].startswith(year)))


def _cashflow(book: Ledger, year: str = "2026", **params: str) -> Any:
    response = book.client.get(
        f"{book.base}/cash-flow-statement",
        headers=book.company.headers,
        params={"fiscal_year_id": _fy(book, year), **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _values(result: Any) -> dict[str, int]:
    return {
        line["code"]: int(line["amount"])
        for line in result["lines"]
        if not line["is_section"] and int(line["amount"]) != 0
    }


@pytest.fixture
def book(client: TestClient, make_company: MakeCompany) -> Ledger:
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
    ledger.create([("601", 999, 0), ("401", 0, 999)], entry_date="2026-03-25")  # brouillon exclu
    return ledger


def test_tft_de_reference(book: Ledger) -> None:
    result = _cashflow(book)
    assert result["coherent"] is True
    assert result["unmapped_accounts"] == []
    assert result["opening"] == "0"
    assert _values(result) == {
        "OA": 1_180_000,  # encaissement client (TVA incluse)
        "FA": 5_000_000,  # capital encaissé
        "XA": 1_180_000,
        "XC": 5_000_000,
        "XV": 6_180_000,
        "TC": 6_180_000,
    }  # TO vaut 0 (assertion dédiée ci-dessus) et est masqué par _values


def test_ventilation_d_une_ecriture_multi_contreparties(book: Ledger) -> None:
    book.posted([("601", 400_000, 0), ("401", 0, 400_000)], journal="AC", entry_date="2026-03-05")
    book.posted(
        [("521", 1_000_000, 0), ("161", 0, 1_000_000)], journal="BQ", entry_date="2026-04-01"
    )
    # Remboursement du capital + intérêts payés en une seule écriture : les deux
    # contreparties vont sur des lignes différentes du TFT.
    book.posted(
        [("161", 500_000, 0), ("671", 50_000, 0), ("521", 0, 550_000)],
        journal="BQ",
        entry_date="2026-09-30",
    )
    values = _values(_cashflow(book))
    assert values["FC"] == 1_000_000
    assert values["FD"] == -500_000
    assert values["OG"] == -50_000
    # Les deux écritures 601/401 (fixture + ce test) ne touchent pas la trésorerie :
    # XA = encaissement client moins les intérêts payés.
    assert values["XA"] == 1_180_000 - 50_000


def test_achats_ventes_cessions_et_subventions(book: Ledger) -> None:
    book.posted(
        [("244", 2_000_000, 0), ("521", 0, 2_000_000)], journal="BQ", entry_date="2026-06-01"
    )
    book.posted([("521", 800_000, 0), ("754", 0, 800_000)], journal="BQ", entry_date="2026-06-15")
    book.posted([("521", 200_000, 0), ("141", 0, 200_000)], journal="BQ", entry_date="2026-07-01")
    book.posted([("571", 100_000, 0), ("521", 0, 100_000)], journal="BQ", entry_date="2026-07-02")
    values = _values(_cashflow(book))
    assert values["IB"] == -2_000_000  # acquisition d'immobilisation corporelle
    assert values["ID"] == 800_000  # cession encaissée
    assert values["FE"] == 200_000  # subvention d'investissement reçue
    assert values["OA"] == 1_180_000  # le virement interne n'ajoute aucun flux
    assert values["XV"] == 6_180_000 - 2_000_000 + 800_000 + 200_000
    assert values["TC"] == values["XV"]


def test_ouverture_par_les_a_nouveaux_et_comparatif(
    client: TestClient, make_company: MakeCompany
) -> None:
    ledger = Ledger(client, make_company())
    ledger.posted(
        [("521", 3_000_000, 0), ("101", 0, 3_000_000)], journal="AN", entry_date="2026-01-01"
    )
    drafts = ledger.client.get(
        f"{ledger.base}/entries", headers=ledger.company.headers, params={"status": "DRAFT"}
    ).json()["items"]
    for draft in drafts:
        ledger.client.delete(f"{ledger.base}/entries/{draft['id']}", headers=ledger.company.headers)
    ledger.client.post(
        f"{ledger.base}/fiscal-years",
        headers=ledger.company.headers,
        json={"start_date": "2027-01-01", "end_date": "2027-12-31"},
    )
    closed = ledger.client.post(
        f"{ledger.base}/fiscal-years/{_fy(ledger, '2026')}/closing", headers=ledger.company.headers
    )
    assert closed.status_code == 200, closed.text
    ledger.posted([("571", 400_000, 0), ("701", 0, 400_000)], journal="VT", entry_date="2027-03-01")
    result = _cashflow(ledger, "2027")
    # L'ouverture 2027 vient des à-nouveaux (origine CLOSING, datées du 1er janvier).
    assert result["opening"] == "3000000"
    values = _values(result)
    assert values["OA"] == 400_000
    assert values["XV"] == 400_000
    assert values["TC"] == 3_400_000
    assert result["coherent"] is True
    assert result["previous_period"] is not None
    fa = next(line for line in result["lines"] if line["code"] == "FA")
    assert (fa["amount"], fa["previous_amount"]) == ("0", "3000000")


def test_tft_a_une_date(book: Ledger) -> None:
    values = _values(_cashflow(book, date_to="2026-02-28"))
    assert "OA" not in values  # l'encaissement du 20 mars n'est pas encore passé
    assert values["FA"] == 5_000_000
    assert _cashflow(book, date_to="2026-02-28")["period"]["date_to"] == "2026-02-28"


def test_le_tft_est_toujours_coherent(client: TestClient, make_company: MakeCompany) -> None:
    ledger = Ledger(client, make_company())
    numbers = [n for n, _ in reference_chart() if not n.startswith("5")]
    treasury = ["521", "571", "522", "531", "552"]
    leaves = [n for n in numbers if not any(o != n and o.startswith(n) for o in numbers)]
    rng = random.Random(17)
    for _ in range(40):
        kind = rng.randint(0, 2)
        amount = rng.randint(1, 10**8)
        if kind == 0:  # trésorerie ↔ divers : flux réel
            ledger.posted(
                [(rng.choice(treasury), amount, 0), (rng.choice(leaves), 0, amount)],
                entry_date=f"2026-{rng.randint(1, 12):02d}-10",
            )
        elif kind == 1:  # virement interne : aucun flux
            ledger.posted(
                [(rng.choice(treasury), amount, 0), (rng.choice(treasury), 0, amount)],
                journal="BQ",
                entry_date=f"2026-{rng.randint(1, 12):02d}-10",
            )
        else:  # sans trésorerie : aucun flux
            ledger.posted(
                [(rng.choice(leaves), amount, 0), (rng.choice(leaves), 0, amount)],
                entry_date=f"2026-{rng.randint(1, 12):02d}-10",
            )
    result = _cashflow(ledger)
    assert result["unmapped_accounts"] == []
    assert result["coherent"] is True
    values = _values(result)
    assert values["TC"] == int(result["opening"]) + values["XV"]


def test_contrepartie_sans_affectation_signalee() -> None:
    # Garde-fou unitaire : un compte hors plan resterait signalé, jamais ignoré.
    assert cashflows.mapping_for("9999") is None
