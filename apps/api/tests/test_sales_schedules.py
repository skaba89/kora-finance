"""Échéanciers clients (lot B-4).

Recette : l'échéancier d'une facture émise planifie ses tranches de règlement
(date attendue, montant attendu) — un **outil de recouvrement** qui n'écrit
jamais en comptabilité et ne modifie jamais le solde. Le plan est remplacé en
bloc (PUT idempotent, tranches renumérotées 1..N), la somme planifiée ne
dépasse jamais le solde restant dû (contrôlé sous verrou FOR UPDATE du
document, sérialisé avec les règlements 4C), et le statut des tranches est
calculé en lecture : les encaissements lettrés couvrent les lignes dans
l'ordre. Vérifie aussi les refus (brouillon, devis, avoir, facture annulée,
plan excédentaire), l'isolation RLS, les permissions, le journal d'audit et la
course règlement/échéancier sur le même verrou de document.
"""

import threading
from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from httpx2 import Response

from kora.models.common import utcnow
from tests.conftest import CompanyFixture
from tests.test_sales import (
    Sales,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)
FUTUR = timedelta(days=365)
PASSE = timedelta(days=365)


class Schedules:
    """Raccourcis d'appel à l'API échéanciers pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def get(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/sales/{document_id}/schedule", headers=headers)

    def put(
        self,
        document_id: str,
        lines: list[dict[str, object]],
        company: CompanyFixture | None = None,
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.put(
            f"{self.base}/sales/{document_id}/schedule", headers=headers, json={"lines": lines}
        )

    def list(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/receivables/schedules", headers=headers, params=query)


def _facture_emise(sales: Sales, client: TestClient, company: CompanyFixture) -> str:
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company))
    assert sales.issue(invoice_id).status_code == 200
    return invoice_id


def _reglement(
    client: TestClient, company: CompanyFixture, invoice_id: str, montant: int
) -> Response:
    """Encaissement sur la facture, daté dans l'exercice ouvert du dossier
    (l'exercice du jeu de données de test couvre 2026)."""
    return client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": montant}],
        },
    )


def test_put_pose_le_plan_et_le_get_le_statue(
    client: TestClient, make_company: MakeCompany
) -> None:
    """PUT idempotent : le plan est posé en bloc, renuméroté 1..N, statué en
    lecture (à venir pour des dates futures) et répété sans effet de bord."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    echeanciers = Schedules(client, company)
    invoice_id = _facture_emise(sales, client, company)
    jour = utcnow().date()
    plan = [
        {
            "expected_on": (jour + FUTUR).isoformat(),
            "expected_amount": 2_000_000,
            "note": "Livraison",
        },
        {
            "expected_on": (jour + FUTUR + timedelta(days=90)).isoformat(),
            "expected_amount": 1_540_000,
        },
    ]
    response = echeanciers.put(invoice_id, plan)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [ligne["line_no"] for ligne in body["lines"]] == [1, 2]
    assert body["planned_total"] == TTC
    assert body["outstanding_ttc"] == TTC
    assert body["paid_ttc"] == 0
    assert all(ligne["status"] == "upcoming" for ligne in body["lines"])
    assert body["lines"][0]["note"] == "Livraison"
    assert body["lines"][1]["note"] is None
    assert body["currency"] == "GNF"

    # Idempotence : répéter le même plan laisse le même état (renumérotation 1..N).
    again = echeanciers.put(invoice_id, plan).json()
    assert again["planned_total"] == TTC
    assert [ligne["line_no"] for ligne in again["lines"]] == [1, 2]

    # Le journal d'audit trace chaque remplacement.
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    actions = [e["action"] for e in (journal["items"] if isinstance(journal, dict) else journal)]
    assert actions.count("sales_schedule.updated") == 2


def test_reglements_couvent_les_tranches_dans_lordre(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Le statut est calculé en lecture : un encaissement de 2 000 000 couvre la
    première tranche (réglée), la seconde reste à venir ; une date passée sans
    couverture est en retard, à un as_of arbitraire comme au jour présent."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    echeanciers = Schedules(client, company)
    invoice_id = _facture_emise(sales, client, company)
    jour = utcnow().date()
    echeanciers.put(
        invoice_id,
        [
            {"expected_on": (jour - PASSE).isoformat(), "expected_amount": 2_000_000},
            {"expected_on": (jour + FUTUR).isoformat(), "expected_amount": 1_540_000},
        ],
    )
    reponse = _reglement(client, company, invoice_id, 2_000_000)
    assert reponse.status_code == 201, reponse.text
    body = echeanciers.get(invoice_id).json()
    assert body["paid_ttc"] == 2_000_000
    assert body["lines"][0]["status"] == "settled"  # cumul encaissé ≥ cumul attendu
    assert body["lines"][1]["status"] == "upcoming"  # date future, non couverte

    # Sans encaissement, la première tranche passée serait « en retard » :
    # lecture à un as_of arbitraire sur une seconde facture.
    autre = _facture_emise(sales, client, company)
    echeanciers.put(
        autre,
        [{"expected_on": (jour - PASSE).isoformat(), "expected_amount": 1_000_000}],
    )
    liste = echeanciers.list().json()
    plan = next(p for p in liste["items"] if p["document_id"] == autre)
    assert plan["lines"][0]["status"] == "late"
    assert plan["outstanding_ttc"] == TTC
    # La même liste à un as_of futur : la tranche non couverte reste en retard,
    # celle du jour futur reste à venir.
    liste_futur = echeanciers.list(as_of=(jour + FUTUR).isoformat()).json()
    plans = {p["document_id"]: p for p in liste_futur["items"]}
    assert plans[autre]["lines"][0]["status"] == "late"


def test_refus_brouillon_devis_avoir_facture_annulee(
    client: TestClient, make_company: MakeCompany
) -> None:
    """L'échéancier concerne une facture ÉMISE uniquement : brouillon (pas
    d'échéance réelle), devis, avoir et facture annulée sont refusés."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    echeanciers = Schedules(client, company)
    tva = _creer_tva(client, company)
    futur = (utcnow().date() + FUTUR).isoformat()
    plan = [{"expected_on": futur, "expected_amount": 1_000}]

    brouillon = _facture_brouillon(sales, tva)
    assert echeanciers.put(brouillon, plan).status_code == 409

    devis = _facture_brouillon(sales, tva, doc_kind="quote")
    assert sales.send(devis).status_code == 200
    assert echeanciers.put(devis, plan).status_code == 409

    avoir = _facture_brouillon(sales, tva, doc_kind="credit_note")
    assert echeanciers.put(avoir, plan).status_code == 409

    annulee = _facture_emise(sales, client, company)
    assert sales.cancel(annulee).status_code == 200
    assert echeanciers.put(annulee, plan).status_code == 409
    # Le GET reste lisible pour tout document du dossier (plan vide ici).
    assert echeanciers.get(brouillon).json()["lines"] == []


def test_plan_excedentaire_et_lignes_invalides_refuses(
    client: TestClient, make_company: MakeCompany
) -> None:
    """La somme du plan ne dépasse jamais le solde restant dû ; montant nul,
    note vide et plus de 24 tranches sont refusés ; après un règlement partiel,
    le plan se cale sur le solde restant."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    echeanciers = Schedules(client, company)
    invoice_id = _facture_emise(sales, client, company)
    futur = (utcnow().date() + FUTUR).isoformat()

    excedent = echeanciers.put(
        invoice_id,
        [
            {"expected_on": futur, "expected_amount": TTC},
            {"expected_on": futur, "expected_amount": 1},
        ],
    )
    assert excedent.status_code == 409, excedent.text  # TTC + 1 > solde

    assert (
        echeanciers.put(invoice_id, [{"expected_on": futur, "expected_amount": 0}]).status_code
        == 422
    )
    assert (
        echeanciers.put(
            invoice_id, [{"expected_on": futur, "expected_amount": 1, "note": " "}]
        ).status_code
        == 422
    )
    assert echeanciers.put(invoice_id, []).status_code == 422
    trop = [{"expected_on": futur, "expected_amount": 1} for _ in range(25)]
    assert echeanciers.put(invoice_id, trop).status_code == 422

    # Après un règlement partiel, le plan est borné au solde restant dû.
    assert _reglement(client, company, invoice_id, 1_000_000).status_code == 201
    assert (
        echeanciers.put(
            invoice_id, [{"expected_on": futur, "expected_amount": TTC - 1_000_000 + 1}]
        ).status_code
        == 409
    )
    ok = echeanciers.put(invoice_id, [{"expected_on": futur, "expected_amount": TTC - 1_000_000}])
    assert ok.status_code == 200, ok.text
    assert ok.json()["planned_total"] == TTC - 1_000_000


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    """Le plan d'un autre dossier est invisible : 404 (jamais 403), et la liste
    ne renvoie que les plans de son propre dossier."""
    mine = Sales(client, _dossier(make_company))
    theirs = Sales(client, _dossier(make_company))
    mes_plans = Schedules(client, mine.company)
    leurs_plans = Schedules(client, theirs.company)
    invoice_id = _facture_emise(mine, client, mine.company)
    futur = (utcnow().date() + FUTUR).isoformat()
    plan = [{"expected_on": futur, "expected_amount": 1_000}]
    assert mes_plans.put(invoice_id, plan).status_code == 200
    assert leurs_plans.get(invoice_id).status_code == 404
    assert leurs_plans.put(invoice_id, plan).status_code == 404
    assert theirs.list().json()["items"] == []
    assert [p["document_id"] for p in leurs_plans.list().json()["items"]] == []


def test_lecteur_lit_mais_ne_planifie_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    invoice_id = _facture_emise(sales, client, company)
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/sales/{invoice_id}/schedule", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/receivables/schedules", headers=headers
        ).status_code
        == 200
    )
    futur = (utcnow().date() + FUTUR).isoformat()
    reponse = client.put(
        f"/api/v1/companies/{company.id}/sales/{invoice_id}/schedule",
        headers=headers,
        json={"lines": [{"expected_on": futur, "expected_amount": 1_000}]},
    )
    assert reponse.status_code == 403


def test_course_reglement_et_echeancier_meme_verrou(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Un encaissement concurrent et un remplacement de plan se sérialisent sur
    le verrou du document : l'un voit le solde réduit de l'autre — jamais de
    plan excédentaire, jamais de lettrage au-delà du solde."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    echeanciers = Schedules(client, company)
    invoice_id = _facture_emise(sales, client, company)
    futur = (utcnow().date() + FUTUR).isoformat()

    barrier = threading.Barrier(2)
    resultats: dict[str, int] = {}

    def _planifier() -> None:
        barrier.wait()
        r = echeanciers.put(invoice_id, [{"expected_on": futur, "expected_amount": TTC}])
        resultats["plan"] = r.status_code

    def _regler() -> None:
        barrier.wait()
        r = _reglement(client, company, invoice_id, TTC)
        resultats["reglement"] = r.status_code

    threads = [threading.Thread(target=_planifier), threading.Thread(target=_regler)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Chaque chemin est valide seul : l'ordre d'exécution décide du résultat.
    # Si le plan gagne, il est posé pour le solde d'alors (le règlement passe
    # ensuite) ; si le règlement gagne, le plan excédentaire est refusé 409.
    assert resultats["reglement"] == 201, resultats
    assert resultats["plan"] in (200, 409), resultats
    body = echeanciers.get(invoice_id).json()
    assert body["outstanding_ttc"] >= 0
    assert body["planned_total"] <= TTC or resultats["plan"] == 409
