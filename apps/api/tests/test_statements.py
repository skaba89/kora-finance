"""Bilan et compte de résultat SYSCOHADA révisé."""

import random
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kora.accounting import statements
from kora.accounting.setup import reference_chart
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]


# --- Référentiel


def test_chaque_compte_du_plan_est_affecte_au_bon_etat() -> None:
    by_code = {line.code: line for line in statements.template()}
    for number, _ in reference_chart():
        mapping = statements.mapping_for(number)
        assert mapping is not None, f"compte {number} sans affectation"
        expected = {"RESULTAT"} if number[0] in "678" else {"ACTIF", "PASSIF"}
        for target in (mapping.if_debit, mapping.if_credit):
            assert by_code[target.code].statement in expected, number


@pytest.mark.parametrize("prefix", ["28", "29", "39", "490", "491", "59", "590"])
def test_amortissements_et_depreciations_en_colonne_dediee(prefix: str) -> None:
    mapping = statements.mapping_for(prefix + "1")
    assert mapping is not None
    assert mapping.if_debit.depreciation
    assert mapping.if_credit.depreciation


def _expand(code: str) -> Counter[str]:
    """Développe un total en somme signée de postes élémentaires."""
    line = {line.code: line for line in statements.template()}[code]
    if line.kind != "total":
        return Counter({code: 1})
    result: Counter[str] = Counter()
    for sign, part in line.formula:
        for leaf, coefficient in _expand(part).items():
            result[leaf] += sign * coefficient
    return result


def test_le_resultat_net_est_produits_moins_charges() -> None:
    lines = statements.template()
    expected = Counter(
        {
            line.code: (1 if line.kind == "produit" else -1)
            for line in lines
            if line.kind in ("produit", "charge")
        }
    )
    assert +_expand("XI") == +expected
    assert {c: v for c, v in _expand("XI").items() if v} == dict(expected)


def test_les_totaux_du_bilan_couvrent_chaque_poste_une_fois() -> None:
    lines = statements.template()
    for statement, total in (("ACTIF", "BZ"), ("PASSIF", "DZ")):
        leaves = {
            line.code for line in lines if line.statement == statement and line.kind == "ligne"
        }
        assert dict(_expand(total)) == dict.fromkeys(leaves, 1)


# --- Calcul sur un jeu de référence


def _fy(book: Ledger, year: str) -> str:
    years = book.client.get(f"{book.base}/fiscal-years", headers=book.company.headers).json()
    return str(next(y["id"] for y in years if y["start_date"].startswith(year)))


def _statements(book: Ledger, year: str = "2026", **params: str) -> Any:
    response = book.client.get(
        f"{book.base}/financial-statements",
        headers=book.company.headers,
        params={"fiscal_year_id": _fy(book, year), **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _values(result: Any) -> dict[str, int]:
    values = {line["code"]: int(line["net"]) for line in result["assets"]}
    values |= {line["code"]: int(line["amount"]) for line in result["liabilities"]}
    values |= {line["code"]: int(line["amount"]) for line in result["income_statement"]}
    return {code: value for code, value in values.items() if value}


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


def test_bilan_et_compte_de_resultat_de_reference(book: Ledger) -> None:
    result = _statements(book)
    assert result["balanced"] is True
    assert result["unmapped_accounts"] == []
    assert result["net_result"] == "600000"
    assert _values(result) == {
        # Actif
        "BS": 6_180_000, "BT": 6_180_000, "BZ": 6_180_000,
        # Passif
        "CA": 5_000_000, "CJ": 600_000, "CP": 5_600_000, "DF": 5_600_000,
        "DJ": 400_000, "DK": 180_000, "DP": 580_000, "DZ": 6_180_000,
        # Compte de résultat
        "TA": 1_000_000, "RA": 400_000, "XA": 600_000, "XB": 1_000_000, "XC": 600_000,
        "XD": 600_000, "XE": 600_000, "XG": 600_000, "XI": 600_000,
    }  # fmt: skip


def test_immobilisation_amortie_et_decouvert(book: Ledger) -> None:
    book.posted(
        [("244", 2_000_000, 0), ("521", 0, 2_000_000)], journal="BQ", entry_date="2026-06-01"
    )
    book.posted([("681", 400_000, 0), ("284", 0, 400_000)], entry_date="2026-12-31")
    book.posted(
        [("661", 6_000_000, 0), ("521", 0, 6_000_000)], journal="BQ", entry_date="2026-12-31"
    )
    result = _statements(book)
    material = next(line for line in result["assets"] if line["code"] == "AM")
    assert (material["gross"], material["depreciation"], material["net"]) == (
        "2000000",
        "400000",
        "1600000",
    )
    values = _values(result)
    # Banque : 6 180 000 - 2 000 000 - 6 000 000 = -1 820 000 → trésorerie-passif.
    assert "BS" not in values
    assert values["DR"] == 1_820_000
    assert values["RK"] == 6_000_000
    assert values["RL"] == 400_000
    assert values["XI"] == 600_000 - 400_000 - 6_000_000
    assert values["CJ"] == values["XI"]
    assert result["balanced"] is True


def test_etats_a_une_date(book: Ledger) -> None:
    values = _values(_statements(book, date_to="2026-02-28"))
    assert values["BI"] == 1_180_000
    assert values["XI"] == 1_000_000
    assert _statements(book, date_to="2026-02-28")["period"]["date_to"] == "2026-02-28"


def test_comparatif_avec_l_exercice_precedent(book: Ledger) -> None:
    # La clôture exige un exercice sans brouillon : on supprime celui du jeu de données.
    drafts = book.client.get(
        f"{book.base}/entries", headers=book.company.headers, params={"status": "DRAFT"}
    ).json()["items"]
    for draft in drafts:
        book.client.delete(f"{book.base}/entries/{draft['id']}", headers=book.company.headers)
    book.client.post(
        f"{book.base}/fiscal-years",
        headers=book.company.headers,
        json={"start_date": "2027-01-01", "end_date": "2027-12-31"},
    )
    closed = book.client.post(
        f"{book.base}/fiscal-years/{_fy(book, '2026')}/closing", headers=book.company.headers
    )
    assert closed.status_code == 200, closed.text
    book.posted([("571", 300_000, 0), ("701", 0, 300_000)], journal="VT", entry_date="2027-03-01")
    result = _statements(book, "2027")
    assert result["previous_period"]["start_date"] == "2026-01-01"
    bz = next(line for line in result["assets"] if line["code"] == "BZ")
    assert (bz["net"], bz["previous_net"]) == ("6480000", "6180000")
    xi = next(line for line in result["income_statement"] if line["code"] == "XI")
    assert (xi["amount"], xi["previous_amount"]) == ("300000", "600000")
    assert result["balanced"] is True


def test_le_bilan_s_equilibre_toujours(client: TestClient, make_company: MakeCompany) -> None:
    ledger = Ledger(client, make_company())
    numbers = [n for n, _ in reference_chart()]
    leaves = [n for n in numbers if not any(o != n and o.startswith(n) for o in numbers)]
    rng = random.Random(42)
    for _ in range(40):
        first, second = rng.sample(leaves, 2)
        amount = rng.randint(1, 10**10)
        ledger.posted(
            [(first, amount, 0), (second, 0, amount)],
            entry_date=f"2026-{rng.randint(1, 12):02d}-10",
        )
    result = _statements(ledger)
    assert result["unmapped_accounts"] == []
    assert result["balanced"] is True
    values = _values(result)
    assert values.get("CJ", 0) == values.get("XI", 0)
