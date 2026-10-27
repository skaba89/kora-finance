"""Tableau de bord : indicateurs calculés sur les écritures validées uniquement."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]


@pytest.fixture
def ledger(client: TestClient, make_company: MakeCompany) -> Ledger:
    return Ledger(client, make_company())


def dashboard(ledger: Ledger, on: str) -> Any:
    response = ledger.client.get(
        f"{ledger.base}/dashboard", headers=ledger.company.headers, params={"on": on}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dossier_sans_ecriture(ledger: Ledger) -> None:
    data = dashboard(ledger, "2026-03-15")
    assert data["fiscal_year"]["start_date"] == "2026-01-01"
    assert data["treasury"] == []
    assert data["treasury_total"] == "0"
    assert data["year_to_date"] == {"revenue": "0", "income": "0", "expenses": "0", "result": "0"}
    assert [m["month"] for m in data["monthly"]] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert data["drafts"] == 0


def test_indicateurs_du_mois_et_de_l_exercice(ledger: Ledger) -> None:
    # À-nouveaux : trésorerie d'ouverture, sans effet sur l'activité de l'exercice.
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    # Février : vente à crédit TTC, achat payé en caisse.
    ledger.posted(
        [("411", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)],
        journal="VT",
        entry_date="2026-02-10",
    )
    ledger.posted([("601", 400_000, 0), ("571", 0, 400_000)], journal="CA", entry_date="2026-02-12")
    # Mars : encaissement partiel du client sur Mobile Money, loyer dû au fournisseur.
    ledger.posted([("552", 700_000, 0), ("411", 0, 700_000)], journal="MM", entry_date="2026-03-05")
    ledger.posted([("622", 250_000, 0), ("401", 0, 250_000)], journal="AC", entry_date="2026-03-08")
    ledger.posted([("706", 0, 300_000), ("571", 300_000, 0)], journal="CA", entry_date="2026-03-09")
    # Après la date demandée et brouillon : ignorés (le brouillon est seulement compté).
    ledger.posted([("571", 999, 0), ("701", 0, 999)], journal="CA", entry_date="2026-03-20")
    assert ledger.create([("571", 1, 0), ("701", 0, 1)], entry_date="2026-03-10").status_code == 201

    data = dashboard(ledger, "2026-03-15")
    assert [(a["number"], a["balance"]) for a in data["treasury"]] == [
        ("521", "5000000"),
        ("552", "700000"),
        ("571", "-100000"),
    ]
    assert data["treasury_total"] == "5600000"
    assert data["receivables"] == "480000"
    assert data["payables"] == "250000"
    assert data["year_to_date"] == {
        "revenue": "1300000",
        "income": "1300000",
        "expenses": "650000",
        "result": "650000",
    }
    assert data["month"] == {
        "revenue": "300000",
        "income": "300000",
        "expenses": "250000",
        "result": "50000",
    }
    assert data["monthly"] == [
        {"month": "2026-01-01", "revenue": "0", "expenses": "0"},
        {"month": "2026-02-01", "revenue": "1000000", "expenses": "400000"},
        {"month": "2026-03-01", "revenue": "300000", "expenses": "250000"},
    ]
    assert data["drafts"] == 1


def test_date_sans_exercice(ledger: Ledger) -> None:
    data = dashboard(ledger, "2025-06-01")
    assert data["fiscal_year"] is None
    assert data["monthly"] == []
    assert data["treasury_total"] == "0"


def test_dossier_d_autrui_invisible(
    ledger: Ledger, client: TestClient, make_company: MakeCompany
) -> None:
    other = make_company()
    response = client.get(f"{ledger.base}/dashboard", headers=other.headers)
    assert response.status_code == 404
