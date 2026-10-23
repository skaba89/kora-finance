"""Plan comptable SYSCOHADA préchargé, personnalisation et taux de taxes versionnés."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kora.accounting.setup import reference_chart
from tests.conftest import CompanyFixture

MakeCompany = Callable[..., CompanyFixture]


def _accounts(client: TestClient, company: CompanyFixture, **params: str | int | bool) -> Any:
    response = client.get(
        f"/api/v1/companies/{company.id}/accounts", headers=company.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_syscohada_precharge(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    page = _accounts(client, company, limit=1)
    assert page["total"] == len(reference_chart()) == 520
    tva = _accounts(client, company, q="4431")["items"]
    assert tva[0] == {
        **tva[0],
        "number": "4431",
        "label": "TVA facturée sur ventes",
        "reference": "SYSCOHADA_REVISE_2017",
        "is_active": True,
    }


def test_recherche_par_libelle_et_par_classe(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    momo = _accounts(client, company, q="téléphone portable")["items"]
    assert [a["number"] for a in momo] == ["552"]
    classe5 = _accounts(client, company, **{"class": 5, "limit": 200})["items"]
    assert all(a["number"].startswith("5") for a in classe5)
    # Les caractères joker SQL sont traités littéralement.
    assert _accounts(client, company, q="%")["total"] == 0


def test_creation_d_un_sous_compte(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    base = f"/api/v1/companies/{company.id}/accounts"
    created = client.post(
        base,
        headers=company.headers,
        json={"number": "5521", "label": "Orange Money – compte principal"},
    )
    assert created.status_code == 201
    assert created.json()["reference"] is None
    duplicate = client.post(
        base, headers=company.headers, json={"number": "5521", "label": "Doublon"}
    )
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    ("number", "status_code"),
    [("9001", 422), ("0401", 422), ("4011001234567", 422), ("401A", 422)],
)
def test_numeros_de_compte_invalides(
    client: TestClient, make_company: MakeCompany, number: str, status_code: int
) -> None:
    company = make_company()
    response = client.post(
        f"/api/v1/companies/{company.id}/accounts",
        headers=company.headers,
        json={"number": number, "label": "Test"},
    )
    assert response.status_code == status_code


def test_compte_de_reference_non_renommable_mais_desactivable(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    account = _accounts(client, company, q="571")["items"][0]
    url = f"/api/v1/companies/{company.id}/accounts/{account['id']}"
    renamed = client.patch(url, headers=company.headers, json={"label": "Ma caisse"})
    assert renamed.status_code == 422
    disabled = client.patch(url, headers=company.headers, json={"is_active": False})
    assert disabled.json()["is_active"] is False
    assert _accounts(client, company, q="571", active_only=True)["total"] == 0


def test_sous_compte_renommable(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    created = client.post(
        f"/api/v1/companies/{company.id}/accounts",
        headers=company.headers,
        json={"number": "4111", "label": "Clients Conakry"},
    ).json()
    renamed = client.patch(
        f"/api/v1/companies/{company.id}/accounts/{created['id']}",
        headers=company.headers,
        json={"label": "Clients – Conakry"},
    )
    assert renamed.json()["label"] == "Clients – Conakry"


# --- Taxes


def _rates(client: TestClient, company: CompanyFixture) -> Any:
    return client.get(f"/api/v1/companies/{company.id}/tax-rates", headers=company.headers).json()


def test_taux_par_defaut_non_verifies(client: TestClient, make_company: MakeCompany) -> None:
    rates = {r["code"]: r for r in _rates(client, make_company())}
    assert rates["TVA_NORMAL"]["rate_basis_points"] == 1800
    assert rates["TVA_NORMAL"]["collected_account_number"] == "4431"
    assert all(r["verified_at"] is None for r in rates.values())
    assert "DGI" in str(rates["TVA_NORMAL"]["note"])


def test_confirmation_d_un_taux(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    rate = next(r for r in _rates(client, company) if r["code"] == "TVA_NORMAL")
    response = client.post(
        f"/api/v1/companies/{company.id}/tax-rates/{rate['id']}/verification",
        headers=company.headers,
    )
    assert response.json()["verified_at"] is not None


def test_nouvelle_version_d_un_taux_clot_la_precedente(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    body = {
        "code": "TVA_NORMAL",
        "label": "TVA – taux normal",
        "kind": "TVA",
        "rate_basis_points": 2000,
        "valid_from": "2027-01-01",
        "collected_account_number": "4431",
        "deductible_account_number": "4452",
    }
    response = client.post(
        f"/api/v1/companies/{company.id}/tax-rates", headers=company.headers, json=body
    )
    assert response.status_code == 201, response.text
    versions = [r for r in _rates(client, company) if r["code"] == "TVA_NORMAL"]
    assert [(v["rate_basis_points"], v["valid_from"], v["valid_to"]) for v in versions] == [
        (2000, "2027-01-01", None),
        (1800, "2000-01-01", "2026-12-31"),
    ]
    # Insérer une version dans le passé de la version en cours est refusé.
    backdated = client.post(
        f"/api/v1/companies/{company.id}/tax-rates",
        headers=company.headers,
        json={**body, "valid_from": "2026-06-01"},
    )
    assert backdated.status_code == 409


def test_taux_avec_compte_inexistant_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    response = client.post(
        f"/api/v1/companies/{company.id}/tax-rates",
        headers=company.headers,
        json={
            "code": "TAXE_X",
            "label": "X",
            "kind": "AUTRE",
            "rate_basis_points": 500,
            "valid_from": "2026-01-01",
            "collected_account_number": "4499",
        },
    )
    assert response.status_code == 422
    assert "4499" in response.json()["detail"]
