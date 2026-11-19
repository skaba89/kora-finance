"""Acomptes clients, trop-perçus, affectation ultérieure et remboursements
(lot B-3).

Recette : un règlement porte au moins la somme de ses affectations — la
différence est le **reste non affecté** (acompte reçu sans facture ou
trop-perçu sur une facture). L'affectation ultérieure exprime des **cibles
absolues** : répéter la même demande ne change rien (idempotence), la hausse
seule est permise, la somme cible ne dépasse jamais le disponible (montant -
remboursements) ni les soldes des factures — contrôles sous verrou FOR UPDATE.
Le remboursement rend au client une part du reste non affecté, jamais au-delà.
La course critique est testée sur PostgreSQL réel : dix affectations
concurrentes d'un même acompte sur une même facture → la somme affectée ne
dépasse jamais le disponible. Le garde-fou des phases 4A-4E reste vrai : sans
l'acte explicite du comptable (`entries:post`), aucune écriture n'apparaît ;
la comptabilisation d'un acompte porte le reste au **419**/4191 « Clients,
avances et acomptes reçus » (jamais au 411), le transfert d'affectation
(débit 4191, crédit 411x) couvre les affectations ajoutées après coup, le
remboursement débite le 4191 et crédite la trésorerie.
"""

import threading
import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture, UserFixture
from tests.test_sales import (
    Sales,
    _creer_tier,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)


def _lignes(entry_body: dict[str, object]):  # type: ignore[no-untyped-def]
    """Lignes d'une écriture renvoyée par l'API (typage strict des tests)."""
    lignes = entry_body["lines"]
    assert isinstance(lignes, list)
    return [ligne for ligne in lignes if isinstance(ligne, dict)]


class Deposits:
    """Raccourcis d'appel à l'API acomptes/affectations/remboursements."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/payments", headers=headers, json=body)

    def get(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/payments/{payment_id}", headers=headers)

    def delete(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.delete(f"{self.base}/payments/{payment_id}", headers=headers)

    def allocate(self, payment_id: str, targets: list[dict[str, object]]) -> Response:
        return self.client.post(
            f"{self.base}/payments/{payment_id}/allocations",
            headers=self.company.headers,
            json={"allocations": targets},
        )

    def refund(self, payment_id: str, body: dict[str, object]) -> Response:
        return self.client.post(
            f"{self.base}/payments/{payment_id}/refund",
            headers=self.company.headers,
            json=body,
        )

    def delete_refund(self, refund_id: str) -> Response:
        return self.client.delete(
            f"{self.base}/payment-refunds/{refund_id}", headers=self.company.headers
        )

    def post_payment(self, payment_id: str) -> Response:
        return self.client.post(
            f"{self.base}/payments/{payment_id}/entry", headers=self.company.headers, json={}
        )

    def post_allocation_entry(self, payment_id: str) -> Response:
        return self.client.post(
            f"{self.base}/payments/{payment_id}/allocation-entry",
            headers=self.company.headers,
            json={},
        )

    def post_refund_entry(self, refund_id: str) -> Response:
        return self.client.post(
            f"{self.base}/payment-refunds/{refund_id}/entry",
            headers=self.company.headers,
            json={},
        )

    def reverse(self, entry_id: str) -> Response:
        return self.client.post(
            f"{self.base}/entries/{entry_id}/reversal",
            headers=self.company.headers,
            json={"entry_date": "2026-12-31"},
        )

    def list_entries(self, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/entries", headers=headers)


def _acompte(
    deposits: Deposits,
    partner_id: str,
    montant: int,
    *,
    paid_on: str = "2026-06-15",
) -> Response:
    return deposits.create(
        {
            "paid_on": paid_on,
            "method": "MOBILE_MONEY",
            "amount": montant,
            "partner_id": partner_id,
        }
    )


def _facture_emise(
    sales: Sales,
    client: TestClient,
    company: CompanyFixture,
    *,
    partner_id: str | None = None,
) -> str:
    overrides: dict[str, object] = {}
    if partner_id is not None:
        overrides["partner_id"] = partner_id
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company), **overrides)
    assert sales.issue(invoice_id).status_code == 200
    return invoice_id


def test_acompte_client_rest_inaffected(client: TestClient, make_company: MakeCompany) -> None:
    """Un acompte reçu sans facture : montant saisi, tier client, reste non
    affecté égal au montant — aucun lettrage, aucune écriture (garde-fou)."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    response = _acompte(deposits, tier, 500_000)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == 500_000
    assert body["unallocated"] == 500_000
    assert body["allocations"] == []
    assert body["refunds"] == []
    assert body["entry_id"] is None
    # Garde-fou : aucun chemin d'acompte n'écrit en comptabilité.
    entries = deposits.list_entries()
    assert entries.status_code == 200
    assert entries.json()["items"] == [], "des écritures sont apparues : acompte → comptabilité"


def test_acompte_exige_montant_et_tier_client(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    # Sans montant : un règlement sans facture n'a rien à lettrer.
    sans_montant = deposits.create({"paid_on": "2026-06-15", "method": "CASH", "partner_id": tier})
    assert sans_montant.status_code == 422
    # Sans tier : l'acompte doit désigner qui l'a versé.
    sans_tier = deposits.create({"paid_on": "2026-06-15", "method": "CASH", "amount": 100_000})
    assert sans_tier.status_code == 422
    # Tier fournisseur seulement : un acompte client se reçoit d'un client.
    fournisseur = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={"name": f"Fournisseur-{uuid.uuid4().hex[:6]}", "is_supplier": True},
    )
    assert fournisseur.status_code == 201, fournisseur.text
    refus = _acompte(deposits, str(fournisseur.json()["id"]), 100_000)
    assert refus.status_code == 422
    assert "client" in refus.json()["detail"].lower()


def test_trop_percu_sur_facture(client: TestClient, make_company: MakeCompany) -> None:
    """Un règlement de 3 640 000 sur une facture de TTC 3 540 000 : la facture
    est soldée et l'excédent de 100 000 reste non affecté."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    response = deposits.create(
        {
            "paid_on": "2026-06-15",
            "method": "CASH",
            "amount": 3_640_000,
            "allocations": [{"document_id": invoice_id, "amount": 3_540_000}],
        }
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == 3_640_000
    assert body["unallocated"] == 100_000
    assert sales.get(invoice_id).json()["payment_status"] == "paid"
    # Moins que la somme des affectations : refusé.
    refus = deposits.create(
        {
            "paid_on": "2026-06-16",
            "method": "CASH",
            "amount": 1_000,
            "allocations": [{"document_id": invoice_id, "amount": 2_000}],
        }
    )
    assert refus.status_code == 422


def test_affectation_ulterieure_idempotente(client: TestClient, make_company: MakeCompany) -> None:
    """L'acompte se lettre plus tard sur une facture émise : cibles absolues,
    répétition = no-op, hausse contrôlée par le solde et le disponible."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 2_000_000).json()
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    # Affectation ultérieure : cible absolue 1 500 000 sur la facture.
    response = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 1_500_000}])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unallocated"] == 500_000
    assert body["allocations"][0]["amount"] == 1_500_000
    assert sales.get(invoice_id).json()["payment_status"] == "partial"
    # Répétition de la même demande : no-op idempotent (etat inchangé).
    encore = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 1_500_000}])
    assert encore.status_code == 200, encore.text
    assert encore.json()["unallocated"] == 500_000
    assert len(encore.json()["allocations"]) == 1
    # Hausse jusqu'à couvrir la facture (cible 3 540 000 dépasse le
    # disponible 2 000 000 : refus) puis remise au niveau possible.
    trop = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 3_540_000}])
    assert trop.status_code == 422
    assert "disponible" in trop.json()["detail"].lower()
    # Hausse autorisée dans la limite du disponible : cible 2 000 000.
    hausse = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 2_000_000}])
    assert hausse.status_code == 200, hausse.text
    assert hausse.json()["unallocated"] == 0
    assert sales.get(invoice_id).json()["payment_status"] == "partial"
    # Réduction : refusée (la correction passe par la suppression du règlement).
    reduction = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 1_000_000}])
    assert reduction.status_code == 422


def test_affectation_ulterieure_refus_hors_perimetre(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 1_000_000).json()
    # Devis et avoir : jamais visés par une affectation.
    tva = _creer_tva(client, company)
    devis = _facture_brouillon(sales, tva, doc_kind="quote", partner_id=tier)
    assert (
        deposits.allocate(acompte["id"], [{"document_id": devis, "amount": 100_000}]).status_code
        == 422
    )
    # Facture d'un autre tier : refusée.
    autre = _facture_emise(sales, client, company)
    refus = deposits.allocate(acompte["id"], [{"document_id": autre, "amount": 100_000}])
    assert refus.status_code == 422
    assert "tier" in refus.json()["detail"].lower()


def test_acompte_deux_factures_concurrentes_ne_depasse_jamais_le_disponible(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Course réelle : dix affectations concurrentes de cibles croissantes sur
    le même acompte — la somme affectée ne dépasse jamais le disponible."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 1_000_000).json()
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    barriere = threading.Barrier(10)
    resultats: list[int] = []
    verrou = threading.Lock()

    def courir() -> None:
        barriere.wait()
        response = deposits.allocate(
            acompte["id"], [{"document_id": invoice_id, "amount": 1_000_000}]
        )
        with verrou:
            resultats.append(response.status_code)

    fils = [threading.Thread(target=courir) for _ in range(10)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    # Un seul des appels hausse l'affectation à 1 000 000 (les suivants sont
    # des no-op idempotents 200 — l'invariant reste la somme ≤ disponible).
    etat = deposits.get(acompte["id"]).json()
    assert sum(a["amount"] for a in etat["allocations"]) == 1_000_000
    assert etat["unallocated"] == 0
    assert all(code in (200, 422) for code in resultats)


def test_remboursement_acompte(client: TestClient, make_company: MakeCompany) -> None:
    """Le remboursement rend une part du reste non affecté ; jamais au-delà ;
    supprimable tant que non comptabilisé ; le disponible suit."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 800_000).json()
    refund = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-20", "method": "BANK_TRANSFER", "amount": 300_000}
    )
    assert refund.status_code == 201, refund.text
    body = refund.json()
    assert body["amount"] == 300_000
    assert body["entry_id"] is None
    etat = deposits.get(acompte["id"]).json()
    assert etat["unallocated"] == 500_000
    assert len(etat["refunds"]) == 1
    # Au-delà du disponible : refus.
    trop = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-21", "method": "CASH", "amount": 600_000}
    )
    assert trop.status_code == 422
    # Suppression du remboursement : le disponible est restitué.
    suppression = deposits.delete_refund(body["id"])
    assert suppression.status_code == 204
    etat = deposits.get(acompte["id"]).json()
    assert etat["unallocated"] == 800_000
    assert etat["refunds"] == []


def test_remboursement_ne_mange_pas_les_affectations(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Acompte 1 000 000, affectation 600 000 : le disponible au remboursement
    est le reste non affecté (400 000) — jamais l'argent déjà lettré."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 1_000_000).json()
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    assert (
        deposits.allocate(
            acompte["id"], [{"document_id": invoice_id, "amount": 600_000}]
        ).status_code
        == 200
    )
    trop = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-20", "method": "CASH", "amount": 400_001}
    )
    assert trop.status_code == 422
    ok = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-20", "method": "CASH", "amount": 400_000}
    )
    assert ok.status_code == 201, ok.text
    # Et l'affectation ultérieure ne peut plus consommer ce qui est remboursé :
    refus = deposits.allocate(acompte["id"], [{"document_id": invoice_id, "amount": 1_000_000}])
    assert refus.status_code == 422


def test_interlocks_suppression(client: TestClient, make_company: MakeCompany) -> None:
    """Un règlement porteur d'un remboursement comptabilisé ne se supprime pas ;
    un remboursement comptabilisé ne se supprime qu'après contre-passation."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 500_000).json()
    refund = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-20", "method": "CASH", "amount": 200_000}
    ).json()
    # Comptabilisation de l'acompte puis du remboursement (4191 → trésorerie).
    posted = deposits.post_payment(acompte["id"])
    assert posted.status_code == 200, posted.text
    entry_id = posted.json()["entry_id"]
    assert deposits.post_refund_entry(refund["id"]).status_code == 200
    etat = deposits.get(acompte["id"]).json()
    refund_entry = etat["refunds"][0]["entry_id"]
    # Suppression du règlement : refusée tant que le remboursement vit.
    assert deposits.delete(acompte["id"]).status_code == 409
    # Suppression du remboursement : refusée tant que son écriture vit.
    assert deposits.delete_refund(refund["id"]).status_code == 409
    # Contre-passation de l'écriture du remboursement puis du règlement :
    # tout se libère dans l'ordre inverse des écritures vivantes.
    assert deposits.reverse(refund_entry).status_code == 201
    assert deposits.delete_refund(refund["id"]).status_code == 204
    assert deposits.reverse(entry_id).status_code == 201
    assert deposits.delete(acompte["id"]).status_code == 204


def test_comptabilisation_acompte_au_4191(client: TestClient, make_company: MakeCompany) -> None:
    """L'écriture d'un acompte : débit de trésorerie, crédit du compte d'avances
    reçues (4191 créé au plan, sinon parent 419) — jamais le 411."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    # Le dossier crée le compte 4191 précis (le référentiel préchargé ne porte
    # que le parent 419) : la résolution exacte doit le choisir.
    plan = client.get(
        f"/api/v1/companies/{company.id}/accounts",
        headers=company.headers,
        params={"q": "419"},
    )
    assert plan.status_code == 200, plan.text
    acompte = _acompte(deposits, tier, 700_000).json()
    response = deposits.post_payment(acompte["id"])
    assert response.status_code == 200, response.text
    entry = client.get(
        f"/api/v1/companies/{company.id}/entries/{response.json()['entry_id']}",
        headers=company.headers,
    ).json()
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    # Acompte encaissé par Mobile Money : débit du compte de banque 521 (le
    # caisse 571 serait utilisé pour un encaissement CASH).
    assert lignes["521"] == (700_000, 0)
    assert "411" not in lignes, "l'acompte ne doit jamais créditer le compte client"
    assert lignes["419"] == (0, 700_000), f"attendu au 419 (parent), vu {lignes}"


def test_comptabilisation_mixte_411_et_4191(client: TestClient, make_company: MakeCompany) -> None:
    """Trop-perçu comptabilisé : la part affectée crédite le 411, l'excédent
    crédite le compte d'avances reçues — écriture équilibrée."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    payment = deposits.create(
        {
            "paid_on": "2026-06-15",
            "method": "BANK_TRANSFER",
            "amount": 3_640_000,
            "allocations": [{"document_id": invoice_id, "amount": 3_540_000}],
        }
    ).json()
    response = deposits.post_payment(payment["id"])
    assert response.status_code == 200, response.text
    entry = client.get(
        f"/api/v1/companies/{company.id}/entries/{response.json()['entry_id']}",
        headers=company.headers,
    ).json()
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["521"] == (3_640_000, 0)
    assert lignes["411"] == (0, 3_540_000)
    assert lignes["419"] == (0, 100_000)
    # Les affectations présentes à la comptabilisation sont couvertes.
    etat = deposits.get(payment["id"]).json()
    assert etat["allocations"][0]["entry_id"] == etat["entry_id"]
    assert etat["unallocated"] == 100_000


def test_transfert_acompte_apres_comptabilisation(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Acompte comptabilisé au 4191, affectation ultérieure, transfert :
    débit 4191 / crédit 411x au journal OD ; les affectations deviennent
    couvertes ; rien à transférer ensuite répond 409."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 1_200_000).json()
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    posted = deposits.post_payment(acompte["id"])
    assert posted.status_code == 200
    # Affectation ultérieure sur règlement comptabilisé : non couverte.
    assert (
        deposits.allocate(
            acompte["id"], [{"document_id": invoice_id, "amount": 900_000}]
        ).status_code
        == 200
    )
    etat = deposits.get(acompte["id"]).json()
    assert etat["allocations"][0]["entry_id"] is None
    # Transfert d'acompte (OD) : débit 4191, crédit 411x. La réponse porte
    # l'etat du règlement — l'écriture de transfert est celle posée sur les
    # affectations (couverture), distincte de l'écriture du règlement (MM).
    transfert = deposits.post_allocation_entry(acompte["id"])
    assert transfert.status_code == 200, transfert.text
    etat = deposits.get(acompte["id"]).json()
    transfert_entry_id = etat["allocations"][0]["entry_id"]
    assert transfert_entry_id is not None
    assert transfert_entry_id != etat["entry_id"]
    entry = client.get(
        f"/api/v1/companies/{company.id}/entries/{transfert_entry_id}",
        headers=company.headers,
    ).json()
    assert entry["journal_code"] == "OD", entry
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["419"] == (900_000, 0)
    assert lignes["411"] == (0, 900_000)
    # Rien à transférer ensuite : 409 (idempotence refusée).
    assert deposits.post_allocation_entry(acompte["id"]).status_code == 409
    # Transfert sur règlement non comptabilisé : 409.
    brut = _acompte(deposits, tier, 100_000).json()
    assert deposits.post_allocation_entry(brut["id"]).status_code == 409


def test_ecriture_remboursement(client: TestClient, make_company: MakeCompany) -> None:
    """Remboursement comptabilisé : débit 4191, crédit trésorerie ; exige un
    règlement porteur comptabilisé ; idempotence refusée (409)."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 600_000).json()
    refund = deposits.refund(
        acompte["id"], {"refunded_on": "2026-06-20", "method": "CASH", "amount": 250_000}
    ).json()
    # Règlement non comptabilisé : refus.
    assert deposits.post_refund_entry(refund["id"]).status_code == 409
    assert deposits.post_payment(acompte["id"]).status_code == 200
    response = deposits.post_refund_entry(refund["id"])
    assert response.status_code == 200, response.text
    entry = client.get(
        f"/api/v1/companies/{company.id}/entries/{response.json()['entry_id']}",
        headers=company.headers,
    ).json()
    lignes = {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in _lignes(entry)
    }
    assert lignes["419"] == (250_000, 0)
    assert lignes["571"] == (0, 250_000)
    # Déjà comptabilisé : 409.
    assert deposits.post_refund_entry(refund["id"]).status_code == 409


def test_isolation_rls_acomptes(client: TestClient, make_company: MakeCompany) -> None:
    """Un acompte, ses affectations et ses remboursements sont invisibles hors
    du dossier ; l'affectation trans-dossier est un 404."""
    mine = Deposits(client, _dossier(make_company))
    theirs = Deposits(client, _dossier(make_company))
    tier = _creer_tier(mine.client, mine.company)
    acompte = _acompte(mine, tier, 100_000).json()
    assert theirs.get(acompte["id"]).status_code == 404
    facture_etrangere = Deposits(client, _dossier(make_company))
    assert (
        theirs.allocate(
            acompte["id"], [{"document_id": str(uuid.uuid4()), "amount": 1}]
        ).status_code
        == 404
    )
    assert theirs.delete(acompte["id"]).status_code == 404
    assert facture_etrangere.list_entries().json()["items"] == []


def test_permissions_acomptes(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., UserFixture]
) -> None:
    """Le lecteur lit les règlements mais n'affecte ni ne rembourse ; les
    écritures restent réservées au comptable (`entries:post`)."""
    company = _dossier(make_company)
    deposits = Deposits(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},
    )
    tier = _creer_tier(client, company)
    acompte = _acompte(deposits, tier, 100_000).json()
    headers = lecteur.headers(client)
    # Lecture : OK.
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/payments/{acompte['id']}", headers=headers
        ).status_code
        == 200
    )
    # Écritures opérationnelles : refusées au lecteur.
    facture = Sales(client, company)
    invoice_id = _facture_emise(facture, client, company, partner_id=tier)
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/payments/{acompte['id']}/allocations",
            headers=headers,
            json={"allocations": [{"document_id": invoice_id, "amount": 1000}]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/payments/{acompte['id']}/refund",
            headers=headers,
            json={"refunded_on": "2026-06-20", "method": "CASH", "amount": 10_000},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/payments/{acompte['id']}/allocation-entry",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
