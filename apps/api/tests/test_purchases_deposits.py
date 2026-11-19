"""Avances fournisseurs, trop-versés, affectation ultérieure et remboursements
(lot B-3, miroir achats).

Recette du miroir complet des acomptes clients appliqué aux dépenses : un
décaissement porte au moins la somme de ses affectations — la différence est le
**reste non affecté** (avance versée sans facture ou trop-versé sur une
facture). L'affectation ultérieure vise des factures fournisseurs émises du
même tier (cibles absolues, idempotentes, hausse seule) ; le remboursement
constate le retour d'une part du reste par le fournisseur. La comptabilisation
d'une avance porte le reste au **409**/4091 « Fournisseurs, avances et acomptes
versés » (jamais au 401), le transfert d'affectation (débit 401x, crédit 4091)
couvre les affectations ajoutées après comptabilisation, le remboursement
débite la trésorerie et crédite le 4091. Garde-fou : sans l'acte explicite du
comptable (`entries:post`), aucune écriture n'apparaît.
"""

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture
from tests.test_purchases import Purchases, _creer_fournisseur, _facture_achat_brouillon
from tests.test_sales import _creer_tva, _dossier

MakeCompany = Callable[..., CompanyFixture]
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)


def _lignes(entry_body: dict[str, object]):  # type: ignore[no-untyped-def]
    """Lignes d'une écriture renvoyée par l'API (typage strict des tests)."""
    lignes = entry_body["lines"]
    assert isinstance(lignes, list)
    return [ligne for ligne in lignes if isinstance(ligne, dict)]


class Advances:
    """Raccourcis d'appel à l'API avances/affectations/remboursements achats."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object]) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payments", headers=self.company.headers, json=body
        )

    def get(self, payment_id: str) -> Response:
        return self.client.get(
            f"{self.base}/purchase-payments/{payment_id}", headers=self.company.headers
        )

    def allocate(self, payment_id: str, targets: list[dict[str, object]]) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payments/{payment_id}/allocations",
            headers=self.company.headers,
            json={"allocations": targets},
        )

    def refund(self, payment_id: str, body: dict[str, object]) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payments/{payment_id}/refund",
            headers=self.company.headers,
            json=body,
        )

    def delete_refund(self, refund_id: str) -> Response:
        return self.client.delete(
            f"{self.base}/purchase-payment-refunds/{refund_id}", headers=self.company.headers
        )

    def post_payment(self, payment_id: str) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payments/{payment_id}/entry",
            headers=self.company.headers,
            json={},
        )

    def post_allocation_entry(self, payment_id: str) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payments/{payment_id}/allocation-entry",
            headers=self.company.headers,
            json={},
        )

    def post_refund_entry(self, refund_id: str) -> Response:
        return self.client.post(
            f"{self.base}/purchase-payment-refunds/{refund_id}/entry",
            headers=self.company.headers,
            json={},
        )

    def entry(self, entry_id: str) -> dict[str, object]:
        response = self.client.get(f"{self.base}/entries/{entry_id}", headers=self.company.headers)
        assert response.status_code == 200, response.text
        body: dict[str, object] = response.json()
        return body

    def list_entries(self) -> Response:
        return self.client.get(f"{self.base}/entries", headers=self.company.headers)


def _avance(advances: Advances, partner_id: str, montant: int) -> Response:
    return advances.create(
        {
            "paid_on": "2026-06-15",
            "method": "BANK_TRANSFER",
            "amount": montant,
            "partner_id": partner_id,
        }
    )


def _facture_achat_emise(
    purchases: Purchases,
    client: TestClient,
    company: CompanyFixture,
    *,
    partner_id: str | None = None,
) -> str:
    overrides: dict[str, object] = {}
    if partner_id is not None:
        overrides["partner_id"] = partner_id
    invoice_id = _facture_achat_brouillon(purchases, _creer_tva(client, company), **overrides)
    assert purchases.issue(invoice_id).status_code == 200
    return invoice_id


def test_avance_fournisseur_rest_inaffectee(client: TestClient, make_company: MakeCompany) -> None:
    """Une avance versée sans facture : montant saisi, tier fournisseur, reste
    non affecté — aucun lettrage, aucune écriture (garde-fou)."""
    company = _dossier(make_company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    response = _avance(advances, fournisseur, 400_000)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == 400_000
    assert body["unallocated"] == 400_000
    assert body["allocations"] == []
    assert body["refunds"] == []
    entries = advances.list_entries()
    assert entries.status_code == 200
    assert entries.json()["items"] == [], "des écritures sont apparues : avance → comptabilité"
    # Tier client seulement : une avance se verse à un fournisseur.
    tier_client = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={"name": f"Client-{uuid.uuid4().hex[:6]}", "is_client": True},
    )
    assert tier_client.status_code == 201
    refus = _avance(advances, str(tier_client.json()["id"]), 100_000)
    assert refus.status_code == 422
    assert "fournisseur" in refus.json()["detail"].lower()


def test_trop_vers_et_affectation_ulterieure(client: TestClient, make_company: MakeCompany) -> None:
    """Décaissement excédentaire : la facture est soldée, l'excédent reste non
    affecté et se lettre plus tard sur une facture émise (cibles absolues)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    facture = _facture_achat_emise(purchases, client, company, partner_id=fournisseur)
    payment = advances.create(
        {
            "paid_on": "2026-06-15",
            "method": "BANK_TRANSFER",
            "amount": 3_640_000,
            "allocations": [{"document_id": facture, "amount": 3_540_000}],
        }
    ).json()
    assert payment["unallocated"] == 100_000
    assert purchases.get(facture).json()["payment_status"] == "paid"
    # Affectation ultérieure sur une deuxième facture du même fournisseur.
    seconde = _facture_achat_emise(purchases, client, company, partner_id=fournisseur)
    reponse = advances.allocate(payment["id"], [{"document_id": seconde, "amount": 100_000}])
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["unallocated"] == 0
    assert purchases.get(seconde).json()["payment_status"] == "partial"
    # Répétition : no-op idempotent.
    encore = advances.allocate(payment["id"], [{"document_id": seconde, "amount": 100_000}])
    assert encore.status_code == 200
    assert encore.json()["unallocated"] == 0
    # Réduction : refusée.
    assert (
        advances.allocate(payment["id"], [{"document_id": seconde, "amount": 50_000}]).status_code
        == 422
    )


def test_remboursement_avance(client: TestClient, make_company: MakeCompany) -> None:
    """Le fournisseur rend une part de l'avance : bornée au reste non affecté,
    supprimable tant que non comptabilisé."""
    company = _dossier(make_company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    avance = _avance(advances, fournisseur, 900_000).json()
    refund = advances.refund(
        avance["id"], {"refunded_on": "2026-06-20", "method": "BANK_TRANSFER", "amount": 350_000}
    )
    assert refund.status_code == 201, refund.text
    assert advances.get(avance["id"]).json()["unallocated"] == 550_000
    trop = advances.refund(
        avance["id"], {"refunded_on": "2026-06-21", "method": "CASH", "amount": 600_000}
    )
    assert trop.status_code == 422
    body = refund.json()
    assert advances.delete_refund(body["id"]).status_code == 204
    assert advances.get(avance["id"]).json()["unallocated"] == 900_000


def test_comptabilisation_avance_au_4091(client: TestClient, make_company: MakeCompany) -> None:
    """Écriture d'une avance : débit du compte d'avances versées (409/4091),
    crédit de trésorerie — jamais le 401."""
    company = _dossier(make_company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    avance = _avance(advances, fournisseur, 600_000).json()
    response = advances.post_payment(avance["id"])
    assert response.status_code == 200, response.text
    entry = advances.entry(response.json()["entry_id"])
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["521"] == (0, 600_000)
    assert "401" not in lignes, "l'avance ne doit jamais débiter le compte fournisseur"
    assert lignes["409"] == (600_000, 0), f"attendu au 409 (parent), vu {lignes}"


def test_transfert_avance_apres_comptabilisation(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Avance comptabilisée au 4091, affectation ultérieure, transfert :
    débit 401x / crédit 4091 au journal OD ; idempotence refusée (409)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    avance = _avance(advances, fournisseur, 1_100_000).json()
    facture = _facture_achat_emise(purchases, client, company, partner_id=fournisseur)
    assert advances.post_payment(avance["id"]).status_code == 200
    assert (
        advances.allocate(avance["id"], [{"document_id": facture, "amount": 800_000}]).status_code
        == 200
    )
    assert advances.get(avance["id"]).json()["allocations"][0]["entry_id"] is None
    transfert = advances.post_allocation_entry(avance["id"])
    assert transfert.status_code == 200, transfert.text
    etat = advances.get(avance["id"]).json()
    transfert_entry_id = etat["allocations"][0]["entry_id"]
    assert transfert_entry_id is not None
    entry = advances.entry(transfert_entry_id)
    assert entry["journal_code"] == "OD", entry
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["401"] == (800_000, 0)
    assert lignes["409"] == (0, 800_000)
    assert advances.post_allocation_entry(avance["id"]).status_code == 409


def test_ecriture_remboursement_achat(client: TestClient, make_company: MakeCompany) -> None:
    """Remboursement reçu du fournisseur : débit trésorerie, crédit 4091 ;
    exige un règlement porteur comptabilisé ; 409 ensuite."""
    company = _dossier(make_company)
    advances = Advances(client, company)
    fournisseur = _creer_fournisseur(client, company)
    avance = _avance(advances, fournisseur, 500_000).json()
    refund = advances.refund(
        avance["id"], {"refunded_on": "2026-06-20", "method": "BANK_TRANSFER", "amount": 200_000}
    ).json()
    assert advances.post_refund_entry(refund["id"]).status_code == 409
    assert advances.post_payment(avance["id"]).status_code == 200
    response = advances.post_refund_entry(refund["id"])
    assert response.status_code == 200, response.text
    entry = advances.entry(response.json()["entry_id"])
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["521"] == (200_000, 0)
    assert lignes["409"] == (0, 200_000)
    assert advances.post_refund_entry(refund["id"]).status_code == 409


def test_isolation_rls_avances(client: TestClient, make_company: MakeCompany) -> None:
    """Une avance d'un autre dossier est invisible (404) : lecture, affectation,
    remboursement, suppression."""
    mine = Advances(client, _dossier(make_company))
    theirs = Advances(client, _dossier(make_company))
    fournisseur = _creer_fournisseur(mine.client, mine.company)
    avance = _avance(mine, fournisseur, 100_000).json()
    assert theirs.get(avance["id"]).status_code == 404
    assert (
        theirs.allocate(avance["id"], [{"document_id": str(uuid.uuid4()), "amount": 1}]).status_code
        == 404
    )
    assert (
        theirs.refund(
            avance["id"], {"refunded_on": "2026-06-20", "method": "CASH", "amount": 1}
        ).status_code
        == 404
    )
