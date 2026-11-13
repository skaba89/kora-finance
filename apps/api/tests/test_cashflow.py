"""Tests d'intégration de la prévision de trésorerie (Phase 3E).

Stratégie de déterminisme : la date de calcul `as_of` est passée explicitement
(2026-06-30) et toutes les écritures sont datées dans l'exercice 2026 créé par la
fixture — le comportement ne dépend pas du jour d'exécution. Le moteur pur est
couvert par `test_cashflow_engine.py` ; ici on vérifie l'API, les droits, l'isolation
multi-tenant, les exclusions documentées et les exports.
"""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

BASE_AS_OF = "2026-06-30"


def _ledger(client: TestClient, make_company: MakeCompany) -> Ledger:
    company = make_company()
    return Ledger(client, company)


def _seed_forecast_data(ledger: Ledger) -> None:
    """Historique 3 mois, virement interne, engagés futurs, brouillon futur.

    - encaissements clients : 2026-03-10 et 2026-05-10, 3 000 000 chacun ;
    - décaissement fournisseur : 2026-04-10, 1 500 000 ;
    - recharge Mobile Money (virement interne) : 2026-05-15, 200 000 — présent dans
      les soldes, absent des flux estimés ;
    - engagés : chèque fournisseur post-daté 2026-07-05 (-800 000), encaissement
      client 2026-07-10 (+1 200 000) ;
    - brouillon futur : 2026-08-01 (-500 000), jamais projeté.
    """
    posted = ledger.posted(
        [("521", 3_000_000, 0), ("411", 0, 3_000_000)],
        journal="BQ",
        entry_date="2026-03-10",
        label="Encaissement client mars",
    )
    assert posted["status"] == "POSTED"
    ledger.posted(
        [("401", 1_500_000, 0), ("521", 0, 1_500_000)],
        journal="BQ",
        entry_date="2026-04-10",
        label="Paiement fournisseur avril",
    )
    ledger.posted(
        [("521", 3_000_000, 0), ("411", 0, 3_000_000)],
        journal="BQ",
        entry_date="2026-05-10",
        label="Encaissement client mai",
    )
    ledger.posted(
        [("552", 200_000, 0), ("521", 0, 200_000)],
        journal="BQ",
        entry_date="2026-05-15",
        label="Recharge Mobile Money",
    )
    ledger.posted(
        [("401", 800_000, 0), ("521", 0, 800_000)],
        journal="BQ",
        entry_date="2026-07-05",
        label="Chèque fournisseur post-daté",
    )
    ledger.posted(
        [("521", 1_200_000, 0), ("411", 0, 1_200_000)],
        journal="BQ",
        entry_date="2026-07-10",
        label="Encaissement client juillet",
    )
    draft = ledger.create(
        [("401", 500_000, 0), ("521", 0, 500_000)],
        journal="BQ",
        entry_date="2026-08-01",
        label="Fournisseur août (brouillon)",
    )
    assert draft.status_code == 201


def _forecast(client: TestClient, ledger: Ledger, **params: str | int) -> dict[str, Any]:
    query: dict[str, str | int] = {
        "as_of": BASE_AS_OF,
        "horizon": 90,
        "scenario": "NEUTRE",
    }
    query.update(params)
    response = client.get(
        f"{ledger.base}/cashflow/forecast",
        headers=ledger.company.headers,
        params=query,
    )
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


# ---------------------------------------------------------------------- calcul


def test_prevision_soldes_engages_estimes(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)

    body = _forecast(client, ledger)

    # OBSERVE : 4 300 000 (521) + 200 000 (552) — le virement interne reste dans les soldes.
    assert body["opening_total"] == "4500000"
    assert body["insufficient_data"] is False
    assert body["history_months_used"] == 3
    assert body["scenario"] == "NEUTRE"

    by_date = {day["flow_date"]: day for day in body["days"]}
    assert by_date["2026-07-05"]["committed_outflow"] == "800000"
    assert by_date["2026-07-10"]["committed_inflow"] == "1200000"

    # ESTIME : moyenne mensuelle sur les 3 mois complets (mars à mai) : encaissements
    # (3 000 000 + 0 + 3 000 000) / 3 = 2 000 000 ; décaissements (0 + 1 500 000 + 0) / 3
    # = 500 000 ; taux journalier = moyenne // jours du mois (31 en juillet).
    assert by_date["2026-07-01"]["estimated_inflow"] == str(2_000_000 // 31)
    assert by_date["2026-07-01"]["estimated_outflow"] == str(500_000 // 31)

    # Le virement interne n'apparaît ni en encaissements ni en décaissements estimés.
    categories_in = body["assumptions"]["categories_inflow"]
    categories_out = body["assumptions"]["categories_outflow"]
    assert categories_in == {"CLIENTS": 6_000_000}
    assert categories_out == {"FOURNISSEURS": 1_500_000}

    # Brouillon futur : listé comme exclusion, jamais projeté.
    drafts = body["excluded_drafts"]
    assert len(drafts) == 1
    assert drafts[0]["entry_date"] == "2026-08-01"
    assert drafts[0]["net_treasury"] == "-500000"
    assert by_date["2026-08-01"]["committed_outflow"] == "0"


def test_prevision_projection_par_compte(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)

    body = _forecast(client, ledger)
    by_number = {account["number"]: account for account in body["accounts"]}
    assert by_number["521"]["opening"] == "4300000"
    # Engagés nets sur l'horizon pour 521 : -800 000 + 1 200 000 = +400 000.
    assert by_number["521"]["committed_net"] == "400000"
    assert by_number["552"]["opening"] == "200000"
    assert by_number["552"]["committed_net"] == "0"


def test_prevision_scenarios_modifient_les_estimes_seulement(
    client: TestClient, make_company: MakeCompany
) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)

    neutre = _forecast(client, ledger)
    optimiste = _forecast(client, ledger, scenario="OPTIMISTE")
    prudent = _forecast(client, ledger, scenario="PRUDENT")

    # Les engagés restent identiques dans les trois scénarios.
    for body in (optimiste, prudent):
        assert body["days"][4]["committed_outflow"] == neutre["days"][4]["committed_outflow"]

    # OPTIMISTE : encaissements estimés ×110 //100, décaissements ×95 //100
    # (moyennes mensuelles 2 000 000 / 500 000, comme dans test_prevision_soldes…).
    assert optimiste["days"][0]["estimated_inflow"] == str((2_000_000 // 31) * 110 // 100)
    assert optimiste["days"][0]["estimated_outflow"] == str((500_000 // 31) * 95 // 100)

    # PRUDENT : encaissements ×80 //100 retardés de 15 jours (J+1 lit le 29/06, 30 jours).
    assert prudent["days"][0]["estimated_inflow"] == str((2_000_000 // 30) * 80 // 100)
    assert (
        prudent["beyond_horizon_inflow"] == "0"
        or int(prudent["beyond_horizon_inflow"]) >= (2_000_000 // 31) * 80 // 100
    )


def test_prevision_historique_vide_insurffisant(
    client: TestClient, make_company: MakeCompany
) -> None:
    ledger = _ledger(client, make_company)
    body = _forecast(client, ledger)
    assert body["insufficient_data"] is True
    assert body["history_months_used"] == 0
    assert all(
        day["estimated_inflow"] == "0" and day["estimated_outflow"] == "0" for day in body["days"]
    )


def test_horizon_invalide_refuse(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    response = client.get(
        f"{ledger.base}/cashflow/forecast",
        headers=ledger.company.headers,
        params={"as_of": BASE_AS_OF, "horizon": 45},
    )
    assert response.status_code == 422


# ------------------------------------------------------------------ tension & seuils


def test_seuil_critique_declenche_la_tension(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)
    raised = client.put(
        f"{ledger.base}/cashflow/settings",
        headers=ledger.company.headers,
        json={
            "critical_floor_minor": 999_999_999,
            "warning_floor_minor": None,
            "default_horizon_days": 90,
            "default_scenario": "NEUTRE",
        },
    )
    assert raised.status_code == 200, raised.text

    body = _forecast(client, ledger)
    assert body["status"] == "CRITIQUE"
    assert body["first_critical_date"] == "2026-07-01"


def test_seuils_aller_retour_et_validation(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    base = f"{ledger.base}/cashflow/settings"
    headers = ledger.company.headers

    vide = client.get(base, headers=headers)
    assert vide.status_code == 200
    assert vide.json()["critical_floor"] == "0"

    saved = client.put(
        base,
        headers=headers,
        json={
            "critical_floor_minor": 1_000_000,
            "warning_floor_minor": 2_500_000,
            "default_horizon_days": 30,
            "default_scenario": "PRUDENT",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["critical_floor"] == "1000000"
    assert client.get(base, headers=headers).json()["default_scenario"] == "PRUDENT"

    incoherent = client.put(
        base,
        headers=headers,
        json={
            "critical_floor_minor": 2_000_000,
            "warning_floor_minor": 1_000_000,
            "default_horizon_days": 30,
            "default_scenario": "NEUTRE",
        },
    )
    assert incoherent.status_code == 422


# --------------------------------------------------------------------- instantanés


def test_instantane_fige_et_isole_par_dossier(
    client: TestClient, make_company: MakeCompany
) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)
    headers = ledger.company.headers

    created = client.post(
        f"{ledger.base}/cashflow/snapshots", headers=headers, params={"scenario": "PRUDENT"}
    )
    assert created.status_code == 201, created.text
    snapshot = created.json()
    assert snapshot["scenario"] == "PRUDENT"
    assert snapshot["assumptions"]["scenario"] == "PRUDENT"

    listed = client.get(f"{ledger.base}/cashflow/snapshots", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [snapshot["id"]]

    # Réalisé : aucune journée passée entre as_of (= aujourd'hui) et maintenant.
    compared = client.get(
        f"{ledger.base}/cashflow/snapshots/{snapshot['id']}/vs-actual", headers=headers
    )
    assert compared.status_code == 200
    assert compared.json()["days"] == []

    # Isolation : un autre dossier du même propriétaire ne voit rien.
    other = make_company(owner=ledger.company.owner)
    other_base = f"/api/v1/companies/{other.id}"
    assert client.get(f"{other_base}/cashflow/snapshots", headers=headers).json() == []
    assert (
        client.get(
            f"{other_base}/cashflow/snapshots/{snapshot['id']}/vs-actual", headers=headers
        ).status_code
        == 404
    )

    # Détail d'un instantané : même contenu que la liste, isolé par dossier.
    detail = client.get(f"{ledger.base}/cashflow/snapshots/{snapshot['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json() == snapshot
    assert (
        client.get(f"{other_base}/cashflow/snapshots/{snapshot['id']}", headers=headers).status_code
        == 404
    )


def test_instantane_d_un_autre_dossier_introuvable(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser
) -> None:
    ledger = _ledger(client, make_company)
    headers = ledger.company.headers
    created = client.post(f"{ledger.base}/cashflow/snapshots", headers=headers)
    assert created.status_code == 201

    intruder = make_user()
    client.post(
        "/api/v1/auth/register",
        json={"email": intruder.email, "password": intruder.password, "full_name": "Autre"},
    )
    other = make_company(owner=intruder)
    response = client.get(
        f"/api/v1/companies/{other.id}/cashflow/snapshots/{created.json()['id']}/vs-actual",
        headers=intruder.headers(client),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- droits


def test_lecteur_consulte_sans_parametrer_ni_figer(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser
) -> None:
    ledger = _ledger(client, make_company)
    reader = make_user()
    added = client.post(
        f"{ledger.base}/members",
        headers=ledger.company.headers,
        json={"email": reader.email, "role": "PME_LECTEUR"},
    )
    assert added.status_code == 201
    headers = reader.headers(client)

    assert (
        client.get(
            f"{ledger.base}/cashflow/forecast",
            headers=headers,
            params={"as_of": BASE_AS_OF, "horizon": 30},
        ).status_code
        == 200
    )
    assert client.get(f"{ledger.base}/cashflow/settings", headers=headers).status_code == 200
    assert client.get(f"{ledger.base}/cashflow/snapshots", headers=headers).status_code == 200

    assert (
        client.put(
            f"{ledger.base}/cashflow/settings",
            headers=headers,
            json={
                "critical_floor_minor": 100,
                "warning_floor_minor": None,
                "default_horizon_days": 30,
                "default_scenario": "NEUTRE",
            },
        ).status_code
        == 403
    )
    assert client.post(f"{ledger.base}/cashflow/snapshots", headers=headers).status_code == 403


# ------------------------------------------------------------------------- exports


def test_export_pdf_et_excel(client: TestClient, make_company: MakeCompany) -> None:
    ledger = _ledger(client, make_company)
    _seed_forecast_data(ledger)
    headers = ledger.company.headers

    for file_format, media in (
        ("pdf", "application/pdf"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ):
        response = client.get(
            f"{ledger.base}/cashflow/forecast/export",
            headers=headers,
            params={"format": file_format, "horizon": 30, "scenario": "NEUTRE"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == media
        assert response.headers["content-disposition"].startswith("attachment")
        assert len(response.content) > 500  # pas un fichier vide
