"""Journaux et écritures : saisie, validation, numérotation, contre-passation."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger, account_id, journal_id

MakeCompany = Callable[..., CompanyFixture]


@pytest.fixture
def ledger(client: TestClient, make_company: MakeCompany) -> Ledger:
    return Ledger(client, make_company())


SALE = [("571", 1_500_000, 0), ("701", 0, 1_500_000)]


def test_journaux_par_defaut(ledger: Ledger) -> None:
    journals = ledger.client.get(f"{ledger.base}/journals", headers=ledger.company.headers).json()
    assert [(j["code"], j["kind"]) for j in journals] == [
        ("AC", "ACHATS"),
        ("AN", "A_NOUVEAUX"),
        ("BQ", "TRESORERIE"),
        ("CA", "TRESORERIE"),
        ("MM", "TRESORERIE"),
        ("OD", "OPERATIONS_DIVERSES"),
        ("VT", "VENTES"),
    ]


def test_creation_et_parametrage_d_un_journal(ledger: Ledger) -> None:
    url = f"{ledger.base}/journals"
    headers = ledger.company.headers
    created = ledger.client.post(
        url, headers=headers, json={"code": "om", "label": "Orange Money", "kind": "TRESORERIE"}
    )
    assert created.status_code == 201
    assert created.json()["code"] == "OM"
    duplicate = ledger.client.post(
        url, headers=headers, json={"code": "OM", "label": "Doublon", "kind": "TRESORERIE"}
    )
    assert duplicate.status_code == 409
    disabled = ledger.client.patch(
        f"{url}/{created.json()['id']}", headers=headers, json={"is_active": False}
    )
    assert disabled.json()["is_active"] is False
    refused = ledger.create(SALE, journal="OM")
    assert refused.status_code == 422
    assert "désactivé" in refused.json()["detail"]


def test_brouillon_puis_validation_numerotee(ledger: Ledger) -> None:
    draft = ledger.create(SALE, journal="VT", label="Vente comptoir")
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["status"] == "DRAFT"
    assert body["number"] is None
    # Montants transmis en chaînes : aucune perte de précision côté JavaScript.
    assert body["total_debit"] == "1500000"
    assert body["lines"][0] == {
        **body["lines"][0],
        "account_number": "571",
        "debit": "1500000",
        "credit": "0",
    }
    posted = ledger.post(body["id"]).json()
    assert posted["status"] == "POSTED"
    assert posted["number"] == 1
    assert posted["posted_at"] is not None
    second = ledger.posted(SALE, journal="VT")
    other_journal = ledger.posted(SALE, journal="CA")
    assert second["number"] == 2
    assert other_journal["number"] == 1


def test_numerotation_par_exercice(ledger: Ledger) -> None:
    ledger.client.post(
        f"{ledger.base}/fiscal-years",
        headers=ledger.company.headers,
        json={"start_date": "2027-01-01", "end_date": "2027-12-31"},
    )
    assert ledger.posted(SALE)["number"] == 1
    assert ledger.posted(SALE, entry_date="2027-02-01")["number"] == 1
    assert ledger.posted(SALE)["number"] == 2


def test_brouillon_desequilibre_accepte_mais_validation_refusee(ledger: Ledger) -> None:
    draft = ledger.create([("571", 1000, 0), ("701", 0, 900)])
    assert draft.status_code == 201
    refused = ledger.post(draft.json()["id"])
    assert refused.status_code == 422
    assert "déséquilibrée" in refused.json()["errors"][0]
    single = ledger.create([("571", 1000, 0)])
    assert ledger.post(single.json()["id"]).json()["errors"][0] == (
        "Une écriture validée comporte au moins deux lignes."
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ({"debit": "100", "credit": "100"}, "pas les deux"),
        ({"debit": "0", "credit": "0"}, "pas les deux"),
    ],
)
def test_ligne_invalide(ledger: Ledger, line: dict[str, str], message: str) -> None:
    body = ledger.body(SALE)
    body["lines"][0].update(line)
    response = ledger.client.post(
        f"{ledger.base}/entries", headers=ledger.company.headers, json=body
    )
    assert response.status_code == 422
    assert message in response.json()["errors"][0]


@pytest.mark.parametrize("amount", ["-5", "12.5", "1e3", "", 12.5, True, "10000000000001"])
def test_montants_non_entiers_ou_hors_limites_refuses(ledger: Ledger, amount: object) -> None:
    body = ledger.body(SALE)
    body["lines"][0]["debit"] = amount
    response = ledger.client.post(
        f"{ledger.base}/entries", headers=ledger.company.headers, json=body
    )
    assert response.status_code == 422


def test_date_hors_exercice(ledger: Ledger) -> None:
    response = ledger.create(SALE, entry_date="2025-12-31")
    assert response.status_code == 422
    assert "Aucun exercice ne couvre le 31/12/2025" in response.json()["detail"]


def test_compte_de_regroupement_refuse(ledger: Ledger) -> None:
    headers = ledger.company.headers
    ledger.client.post(
        f"{ledger.base}/accounts", headers=headers, json={"number": "5711", "label": "Caisse siège"}
    )
    draft = ledger.create(SALE)
    response = ledger.post(draft.json()["id"])
    assert response.status_code == 422
    assert response.json()["errors"] == ["Compte 571"]
    assert ledger.posted([("5711", 1000, 0), ("701", 0, 1000)])["status"] == "POSTED"


def test_compte_desactive_refuse(ledger: Ledger) -> None:
    draft = ledger.create(SALE)
    account = account_id(ledger.client, ledger.base, ledger.company.headers, "701")
    ledger.client.patch(
        f"{ledger.base}/accounts/{account}",
        headers=ledger.company.headers,
        json={"is_active": False},
    )
    response = ledger.post(draft.json()["id"])
    assert response.status_code == 422
    assert "701" in response.json()["detail"]


def test_a_nouveaux_dates_du_premier_jour(ledger: Ledger) -> None:
    lines = [("521", 5_000_000, 0), ("101", 0, 5_000_000)]
    refused = ledger.post(ledger.create(lines, journal="AN", entry_date="2026-01-02").json()["id"])
    assert refused.status_code == 422
    assert "premier jour de l'exercice (01/01/2026)" in refused.json()["detail"]
    assert ledger.posted(lines, journal="AN", entry_date="2026-01-01")["number"] == 1


def test_modification_et_suppression_d_un_brouillon(ledger: Ledger) -> None:
    draft = ledger.create(SALE).json()
    url = f"{ledger.base}/entries/{draft['id']}"
    headers = ledger.company.headers
    updated = ledger.client.put(
        url,
        headers=headers,
        json=ledger.body([("571", 2000, 0), ("701", 0, 2000)], label="Corrigée"),
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Corrigée"
    assert [line["debit"] for line in updated.json()["lines"]] == ["2000", "0"]
    assert ledger.client.delete(url, headers=headers).status_code == 204
    assert ledger.client.get(url, headers=headers).status_code == 404


def test_ecriture_validee_immuable(ledger: Ledger) -> None:
    posted = ledger.posted(SALE)
    url = f"{ledger.base}/entries/{posted['id']}"
    headers = ledger.company.headers
    assert ledger.client.put(url, headers=headers, json=ledger.body(SALE)).status_code == 409
    assert ledger.client.delete(url, headers=headers).status_code == 409
    assert ledger.post(posted["id"]).status_code == 409


def test_contre_passation(ledger: Ledger) -> None:
    posted = ledger.posted(SALE, journal="VT")
    url = f"{ledger.base}/entries/{posted['id']}/reversal"
    headers = ledger.company.headers
    reversal = ledger.client.post(url, headers=headers, json={"entry_date": "2026-03-20"})
    assert reversal.status_code == 201, reversal.text
    body = reversal.json()
    assert body["status"] == "POSTED"
    assert body["number"] == 2
    assert body["reversal_of_id"] == posted["id"]
    assert body["label"].startswith("Contre-passation VT n° 1")
    assert [(ln["account_number"], ln["debit"], ln["credit"]) for ln in body["lines"]] == [
        ("571", "0", "1500000"),
        ("701", "1500000", "0"),
    ]
    original = ledger.client.get(f"{ledger.base}/entries/{posted['id']}", headers=headers).json()
    assert original["reversed_by_id"] == body["id"]
    again = ledger.client.post(url, headers=headers, json={"entry_date": "2026-03-20"})
    assert again.status_code == 409
    of_reversal = ledger.client.post(
        f"{ledger.base}/entries/{body['id']}/reversal",
        headers=headers,
        json={"entry_date": "2026-03-21"},
    )
    assert of_reversal.status_code == 422


def test_brouillon_ne_se_contre_passe_pas(ledger: Ledger) -> None:
    draft = ledger.create(SALE).json()
    response = ledger.client.post(
        f"{ledger.base}/entries/{draft['id']}/reversal",
        headers=ledger.company.headers,
        json={"entry_date": "2026-03-20"},
    )
    assert response.status_code == 422


def test_creation_idempotente_par_identifiant_client(ledger: Ledger) -> None:
    body = {**ledger.body(SALE), "id": str(uuid.uuid4())}
    headers = ledger.company.headers
    first = ledger.client.post(f"{ledger.base}/entries", headers=headers, json=body)
    second = ledger.client.post(f"{ledger.base}/entries", headers=headers, json=body)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    listed = ledger.client.get(f"{ledger.base}/entries", headers=headers).json()
    assert listed["total"] == 1


def test_liste_filtres_et_totaux(ledger: Ledger) -> None:
    ledger.posted(SALE, journal="VT", label="Vente Kaloum")
    ledger.posted([("601", 400_000, 0), ("401", 0, 400_000)], journal="AC", label="Achat farine")
    ledger.create(SALE, label="Brouillon en cours")
    headers = ledger.company.headers
    url = f"{ledger.base}/entries"

    def fetch(**params: str) -> Any:
        return ledger.client.get(url, headers=headers, params=params).json()

    assert fetch()["total"] == 3
    assert [e["label"] for e in fetch(status="DRAFT")["items"]] == ["Brouillon en cours"]
    purchases = fetch(journal_id=journal_id(ledger.client, ledger.base, headers, "AC"))["items"]
    assert [(e["journal_code"], e["total_debit"], e["total_credit"]) for e in purchases] == [
        ("AC", "400000", "400000")
    ]
    assert fetch(q="kaloum")["total"] == 1
    assert fetch(q="%")["total"] == 0
    by_account = fetch(account_id=account_id(ledger.client, ledger.base, headers, "601"))
    assert [e["label"] for e in by_account["items"]] == ["Achat farine"]


def test_idor_journal_et_compte_d_un_autre_dossier(
    client: TestClient, make_company: MakeCompany
) -> None:
    mine, theirs = Ledger(client, make_company()), Ledger(client, make_company())
    their_body = theirs.body(SALE)
    response = client.post(f"{mine.base}/entries", headers=mine.company.headers, json=their_body)
    assert response.status_code == 422
    assert "introuvable" in response.json()["detail"]
    # Journal du dossier, mais compte d'un autre dossier.
    body = mine.body(SALE)
    body["lines"][1]["account_id"] = their_body["lines"][1]["account_id"]
    response = client.post(f"{mine.base}/entries", headers=mine.company.headers, json=body)
    assert response.status_code == 422
    their_entry = theirs.posted(SALE)
    for method, suffix in (("GET", ""), ("POST", "/post"), ("DELETE", "")):
        response = client.request(
            method, f"{mine.base}/entries/{their_entry['id']}{suffix}", headers=mine.company.headers
        )
        assert response.status_code == 404


def test_audit_de_la_validation(ledger: Ledger) -> None:
    posted = ledger.posted(SALE, journal="VT")
    events = ledger.client.get(f"{ledger.base}/audit-events", headers=ledger.company.headers).json()
    event = next(e for e in events["items"] if e["action"] == "entry.posted")
    assert event["entity_id"] == posted["id"]
    assert event["payload"]["total"] == 1_500_000
    assert event["payload"]["lignes"][0] == {"compte": "571", "debit": 1_500_000, "credit": 0}
