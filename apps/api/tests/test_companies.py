"""Dossiers d'entreprise, membres et exercices comptables."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.db.tenant import bind_tenant
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


def test_creation_d_un_dossier_complet(client: TestClient, make_user: MakeUser) -> None:
    owner = make_user()
    headers = owner.headers(client)
    response = client.post(
        "/api/v1/companies",
        headers=headers,
        json={
            "legal_name": "  Kaloum Distribution  ",
            "legal_form": "SARLU",
            "rccm": "GN.TCC.2024.B.01234",
            "nif": "123456789",
            "city": "Conakry",
            "first_fiscal_year": {"start_date": "2026-01-01", "end_date": "2026-12-31"},
        },
    )
    assert response.status_code == 201, response.text
    company = response.json()
    assert company["legal_name"] == "Kaloum Distribution"
    assert company["currency"] == "GNF"

    detail = client.get(f"/api/v1/companies/{company['id']}", headers=headers).json()
    assert detail["role"] == "PME_DIRIGEANT"
    years = client.get(f"/api/v1/companies/{company['id']}/fiscal-years", headers=headers).json()
    assert [(y["start_date"], y["end_date"], y["status"]) for y in years] == [
        ("2026-01-01", "2026-12-31", "OPEN")
    ]


def test_forme_juridique_inconnue_refusee(client: TestClient, make_user: MakeUser) -> None:
    response = client.post(
        "/api/v1/companies",
        headers=make_user().headers(client),
        json={"legal_name": "X", "legal_form": "LLC"},
    )
    assert response.status_code == 422


def test_modification_de_la_fiche_auditee(
    client: TestClient, make_company: MakeCompany, db: Session
) -> None:
    company = make_company()
    response = client.patch(
        f"/api/v1/companies/{company.id}",
        headers=company.headers,
        json={"nif": "987654321", "city": "Kindia"},
    )
    assert response.status_code == 200
    assert response.json()["nif"] == "987654321"

    events = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()["items"]
    update = next(e for e in events if e["action"] == "company.updated")
    assert update["payload"]["city"] == {"avant": None, "apres": "Kindia"}
    bind_tenant(db, company.id)
    assert verify_chain(db).ok


def test_la_devise_n_est_pas_modifiable(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    response = client.patch(
        f"/api/v1/companies/{company.id}", headers=company.headers, json={"currency": "EUR"}
    )
    assert response.status_code == 422


def test_modification_vide_refusee(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    assert (
        client.patch(
            f"/api/v1/companies/{company.id}", headers=company.headers, json={}
        ).status_code
        == 422
    )


# --- Membres


def test_ajout_changement_et_retrait_d_un_membre(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser
) -> None:
    company = make_company()
    base = f"/api/v1/companies/{company.id}/members"
    colleague = make_user()
    added = client.post(
        base,
        headers=company.headers,
        json={"email": colleague.email.upper(), "role": "PME_COMPTABLE"},
    )
    assert added.status_code == 201
    assert added.json()["status"] == "member"
    member_id = added.json()["member"]["id"]

    duplicate = client.post(
        base, headers=company.headers, json={"email": colleague.email, "role": "PME_LECTEUR"}
    )
    assert duplicate.status_code == 409

    changed = client.patch(
        f"{base}/{member_id}", headers=company.headers, json={"role": "PME_LECTEUR"}
    )
    assert changed.json()["role"] == "PME_LECTEUR"

    assert client.delete(f"{base}/{member_id}", headers=company.headers).status_code == 204
    assert (
        client.get(f"/api/v1/companies/{company.id}", headers=colleague.headers(client)).status_code
        == 404
    )


@pytest.mark.parametrize("role", ["CABINET_ADMIN", "SUPER_ADMIN", "PARTENAIRE_FINANCIER"])
def test_roles_non_attribuables_sur_un_dossier(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser, role: str
) -> None:
    company = make_company()
    response = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": make_user().email, "role": role},
    )
    assert response.status_code == 422


def test_le_dernier_dirigeant_ne_peut_pas_partir(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    base = f"/api/v1/companies/{company.id}/members"
    me = client.get(base, headers=company.headers).json()[0]["id"]
    assert client.delete(f"{base}/{me}", headers=company.headers).status_code == 422
    demoted = client.patch(f"{base}/{me}", headers=company.headers, json={"role": "PME_LECTEUR"})
    assert demoted.status_code == 422
    assert demoted.json()["detail"] == "Le dossier doit conserver au moins un dirigeant."


# --- Exercices


@pytest.mark.parametrize(
    ("start", "end", "status_code"),
    [
        ("2026-06-01", "2027-05-31", 409),  # chevauche 2026
        ("2026-12-31", "2027-12-31", 409),  # chevauche d'un jour
        ("2027-01-01", "2027-12-31", 201),
        ("2027-01-01", "2026-12-31", 422),  # dates inversées
        ("2027-01-01", "2029-01-01", 422),  # plus de 24 mois
        ("2027-01-01", "2028-12-31", 201),  # 24 mois exactement
    ],
)
def test_regles_des_exercices(
    client: TestClient, make_company: MakeCompany, start: str, end: str, status_code: int
) -> None:
    company = make_company()
    response = client.post(
        f"/api/v1/companies/{company.id}/fiscal-years",
        headers=company.headers,
        json={"start_date": start, "end_date": end},
    )
    assert response.status_code == status_code, response.text


def test_exercices_independants_entre_dossiers(
    client: TestClient, make_company: MakeCompany
) -> None:
    # Le non-chevauchement s'apprécie par dossier : deux dossiers ont le même exercice 2026.
    first, second = make_company(), make_company()
    for company in (first, second):
        years = client.get(
            f"/api/v1/companies/{company.id}/fiscal-years", headers=company.headers
        ).json()
        assert len(years) == 1
