"""Décaissements fournisseurs et lettrage commercial des achats (Phase 4F).

Miroir des règlements clients (4C) appliqué aux dettes : le montant d'un
décaissement est la somme stricte de ses affectations (jamais saisi), le solde
restant dû d'une facture fournisseur se calcule en lecture (TTC - affectations -
avoirs partiels émis), et la course critique est symétrique : vingt règlements
concurrents de 1 000 sur un TTC de 10 000 = dix succès + dix refus 422, somme
lettrée exactement 10 000. Un avoir partiel réduit le solde ; une facture qui
porte des décaissements ne s'annule plus ; la suppression d'un règlement
journalisé libère les soldes. L'échéancier fournisseurs répartit les dettes par
ancienneté de retard. Le garde-fou comptable reste vrai : aucun encaissement ni
décaissement n'écrit au grand livre (4F ne comptabilise que sur acte explicite).
"""

import threading
from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from httpx2 import Response

from kora.models.common import utcnow
from tests.conftest import CompanyFixture
from tests.test_purchases import Purchases, _facture_achat_brouillon
from tests.test_sales import _creer_tva, _dossier

MakeCompany = Callable[..., CompanyFixture]


class Disbursements:
    """Raccourcis d'appel à l'API décaissements fournisseurs."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/purchase-payments", headers=headers, json=body)

    def list(self, **params: object) -> Response:
        query: dict[str, str] = {k: str(v) for k, v in params.items()}
        return self.client.get(
            f"{self.base}/purchase-payments", headers=self.company.headers, params=query
        )

    def get(self, payment_id: str) -> Response:
        return self.client.get(
            f"{self.base}/purchase-payments/{payment_id}", headers=self.company.headers
        )

    def delete(self, payment_id: str) -> Response:
        return self.client.delete(
            f"{self.base}/purchase-payments/{payment_id}", headers=self.company.headers
        )


def _facture_emise(purchases: Purchases, tva_id: str | None = None) -> str:
    doc_id = _facture_achat_brouillon(purchases, tva_id)
    assert purchases.issue(doc_id).status_code == 200, purchases.issue(doc_id).text
    return doc_id


def _decaissement(
    client: TestClient,
    company: CompanyFixture,
    document_id: str,
    amount: int,
    *,
    paid_on: str = "2026-06-15",
    method: str = "BANK_TRANSFER",
) -> Response:
    return client.post(
        f"/api/v1/companies/{company.id}/purchase-payments",
        headers=company.headers,
        json={
            "paid_on": paid_on,
            "method": method,
            "allocations": [{"document_id": document_id, "amount": amount}],
        },
    )


def test_montant_recalcule_somme_des_affectations(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Le montant du décaissement est recalculé par le service : la somme de ses
    affectations, jamais saisi."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    invoice_id = _facture_emise(purchases)
    reponse = client.post(
        f"/api/v1/companies/{company.id}/purchase-payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [
                {"document_id": invoice_id, "amount": 4_000},
            ],
        },
    )
    assert reponse.status_code == 201, reponse.text
    payment = reponse.json()
    assert payment["amount"] == 4_000
    assert payment["entry_id"] is None
    facture = purchases.get(invoice_id).json()
    assert facture["outstanding_ttc"] == facture["total_ttc"] - 4_000
    assert facture["payment_status"] == "partial"


def test_reglements_concurrents_sans_excedent(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Course critique : vingt décaissements concurrents de 1 000 sur une facture
    de TTC 10 000 → exactement dix succès, aucun excédent, solde zéro."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    petite = _facture_achat_brouillon(
        purchases,
        lines=[
            {
                "label": "Marchandise de démonstration",
                "quantity": 1000,
                "unit_price_ht": 10_000,
                "tax_exempt_reason": "Achat exonéré (article du CGI à documenter)",
            }
        ],
    )
    assert purchases.issue(petite).status_code == 200

    resultats: list[str] = []
    verrou = threading.Lock()

    def regler() -> None:
        try:
            reponse = _decaissement(client, company, petite, 1_000)
            with verrou:
                resultats.append(str(reponse.status_code))
        except BaseException as exc:  # pragma: no cover - diagnostic de course
            with verrou:
                resultats.append(f"EXC {exc!r}")

    fils = [threading.Thread(target=regler) for _ in range(20)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(30)
        assert not fil.is_alive(), "décaissement bloqué > 30 s"

    assert resultats.count("201") == 10, sorted(resultats)
    assert resultats.count("422") == 10, sorted(resultats)
    facture = purchases.get(petite).json()
    assert facture["outstanding_ttc"] == 0
    assert facture["payment_status"] == "paid"


def test_excedent_refuse_et_avoir_partiel_reduit_le_solde(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Un décaissement au-delà du solde restant dû est refusé ; un avoir
    fournisseur partiel émis réduit le solde de la facture."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    invoice_id = _facture_emise(purchases, tva_id)
    facture = purchases.get(invoice_id).json()
    ttc = facture["total_ttc"]
    excedent = _decaissement(client, company, invoice_id, ttc + 1)
    assert excedent.status_code == 422, excedent.text
    # Avoir partiel : la moitié du TTC, sans annuler la facture.
    avoir = purchases.create(
        {
            "doc_kind": "supplier_credit_note",
            "partner_id": facture["partner_id"],
            "lines": [
                {
                    "label": "Remise accordée sur la moitié",
                    "quantity": 1000,
                    "unit_price_ht": ttc // 2,
                    "tax_exempt_reason": "Ajustement partiel (remise fournisseur)",
                }
            ],
            "origin_document_id": invoice_id,
        }
    )
    assert avoir.status_code == 201, avoir.text
    assert purchases.issue(avoir.json()["id"]).status_code == 200
    facture = purchases.get(invoice_id).json()
    assert facture["outstanding_ttc"] == ttc - ttc // 2, "l'avoir partiel réduit le solde"
    # Le solde réduite accepte maintenant un décaissement inférieur au nouveau solde.
    reponse = _decaissement(client, company, invoice_id, facture["outstanding_ttc"])
    assert reponse.status_code == 201, reponse.text
    assert purchases.get(invoice_id).json()["payment_status"] == "paid"


def test_facture_lettree_ne_sannule_pas(client: TestClient, make_company: MakeCompany) -> None:
    """Une facture qui porte des décaissements refuse l'annulation (ni sans avoir,
    ni par avoir) : les décaissements se suppriment d'abord."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    factures = Disbursements(client, company)
    invoice_id = _facture_emise(purchases)
    assert _decaissement(client, company, invoice_id, 1_000).status_code == 201
    assert purchases.cancel(invoice_id).status_code == 409
    # La suppression du décaissement libère l'annulation.
    payment_id = factures.list(limit=1).json()["items"][0]["id"]
    assert factures.delete(payment_id).status_code == 204
    assert purchases.cancel(invoice_id).status_code == 200


def test_decaissement_devise_et_tier_controles(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Un décaissement s'affecte aux factures d'un seul fournisseur."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    f1 = _facture_emise(purchases)
    f2 = _facture_emise(purchases)
    reponse = client.post(
        f"/api/v1/companies/{company.id}/purchase-payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [
                {"document_id": f1, "amount": 500},
                {"document_id": f2, "amount": 500},
            ],
        },
    )
    assert reponse.status_code == 422, reponse.text
    assert "seul" in reponse.json()["detail"].lower()


def test_payables_aging_buckets(client: TestClient, make_company: MakeCompany) -> None:
    """Échéancier fournisseurs : une facture à échéance lointaine entre dans
    not_due ; une facture échue de 45 jours entre dans d31_60. Échéances
    **dynamiques** : aucune date calendaire en dur (un jour en dur restait vert
    jusqu'à sa date, puis cassait chaque jour suivant)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    future = utcnow().date() + timedelta(days=45)
    passee = utcnow().date() - timedelta(days=45)
    non_echue = _facture_achat_brouillon(purchases, tva_id, due_on=future.isoformat())
    assert purchases.issue(non_echue).status_code == 200
    # Facture échue : brouillon créé avec échéance future (la création refuse
    # une échéance passée), échéance corrigée sur le brouillon, émission
    # rétrodatée à la date du fournisseur (rattrapage de saisie).
    echue = _facture_achat_brouillon(purchases, tva_id, due_on=future.isoformat())
    patched = purchases.patch(echue, {"due_on": passee.isoformat()})
    assert patched.status_code == 200, patched.text
    response = purchases.issue(echue, issued_on=passee.isoformat())
    assert response.status_code == 200, response.text
    aging = client.get(
        f"/api/v1/companies/{company.id}/payables/aging",
        headers=company.headers,
        params={"as_of": utcnow().date().isoformat()},  # 45 jours après l'échéance
    ).json()
    assert aging["buckets"]["not_due"]["count"] == 1
    assert aging["buckets"]["d31_60"]["count"] == 1, aging["buckets"]
    total_attendu = (
        purchases.get(non_echue).json()["total_ttc"] + purchases.get(echue).json()["total_ttc"]
    )
    assert aging["grand_total_ttc"] == total_attendu
